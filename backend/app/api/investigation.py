from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field

from app.ai.llm_client import LLMError
from app.ai.reasoner import diagnose
from app.insforge.auth import AuthUser, current_user
from app.insforge.history import InvestigationHistory
from app.kubernetes.clusters import (
    ClusterInfo,
    UnknownClusterError,
    cluster_args,
    find_cluster,
    list_clusters_with_status,
)
from app.kubernetes.executor import KubectlError, use_cluster
from app.models.investigation import InvestigateRequest, InvestigateResponse
from app.services.investigation import investigate_cluster

router = APIRouter()

UNEXPECTED_HINTS = ["Try again", "If it keeps happening, check the backend logs (`docker compose logs backend`)"]


class _NoHistory:
    """Used when auth is turned off: same methods as InvestigationHistory, does nothing."""

    id = None

    def start(self, cluster: str | None = None) -> None: ...
    def step(self, name: str) -> None: ...
    def finish(self, *args, **kwargs) -> None: ...


class ClustersResponse(BaseModel):
    clusters: list[ClusterInfo] = Field(default_factory=list)
    error: str | None = None
    hints: list[str] = Field(default_factory=list)


@router.get("/clusters", response_model=ClustersResponse)
def clusters(user: AuthUser | None = Depends(current_user)) -> ClustersResponse | JSONResponse:
    """Every cluster (kubeconfig context) the backend can see, with a quick reachability check."""
    try:
        return ClustersResponse(clusters=list_clusters_with_status())
    except KubectlError as exc:
        return ClustersResponse(error=str(exc), hints=exc.hints)
    except Exception:
        logger.exception("Listing clusters failed")
        body = ClustersResponse(error="Could not read your clusters.", hints=UNEXPECTED_HINTS)
        return JSONResponse(status_code=500, content=body.model_dump(mode="json"))


def _error(status_code: int, message: str, hints: list[str], **extra) -> JSONResponse:
    body = InvestigateResponse(status="error", error=message, hints=hints, **extra)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


# A plain `def` (not async) so FastAPI runs the blocking kubectl and HTTP calls in a worker thread.
@router.post(
    "/investigate",
    response_model=InvestigateResponse,
    responses={
        400: {"model": InvestigateResponse, "description": "Unknown cluster"},
        401: {"description": "Not signed in, or the session expired"},
        503: {"model": InvestigateResponse, "description": "kubectl missing or cluster unreachable"},
    },
)
def investigate(
    request: InvestigateRequest | None = None,
    user: AuthUser | None = Depends(current_user),
) -> InvestigateResponse | JSONResponse:
    # Which cluster to investigate (default: the kubeconfig's current context).
    try:
        cluster = find_cluster(request.cluster if request else None)
    except UnknownClusterError as exc:
        return _error(400, str(exc), exc.hints)
    except KubectlError as exc:  # no kubeconfig, no kubectl
        return _error(503, str(exc), exc.hints)

    # History row + realtime progress (InsForge). Best-effort: failures here never stop the investigation.
    history = InvestigationHistory(user.token) if user else _NoHistory()
    history.start(cluster.name)
    logger.info("Investigating cluster '{}' for {}", cluster.name, (user.email or user.id) if user else "anonymous")
    ids = {"investigation_id": history.id, "cluster": cluster.name}

    try:
        # 1. Collect Kubernetes evidence (reports each step as it starts)
        try:
            with use_cluster(cluster_args(cluster)):
                investigation = investigate_cluster(on_step=history.step, cluster_name=cluster.name)
        except KubectlError as exc:
            history.finish("error", error=str(exc))
            return _error(503, str(exc), exc.hints, **ids)

        # 2. AI reasoning: root cause, fix, confidence.
        # If it fails, still return the evidence so the investigation is not wasted.
        history.step("ai")
        try:
            diagnosis = diagnose(investigation)
        except LLMError as exc:
            logger.error("AI diagnosis failed: {}", exc)
            error = f"Evidence was collected, but the AI diagnosis failed: {exc}"
            history.finish("partial", investigation=investigation, error=error)
            return InvestigateResponse(
                status="partial", investigation=investigation, error=error, hints=exc.hints, **ids
            )

        history.finish("success", investigation=investigation, diagnosis=diagnosis)
        return InvestigateResponse(status="success", diagnosis=diagnosis, investigation=investigation, **ids)

    except Exception:
        # Unexpected bug: log the stack trace, show the user a clean message,
        # and mark the history row as failed instead of leaving it "running" forever.
        logger.exception("Investigation crashed")
        history.finish("error", error="Unexpected server error")
        return _error(500, "Something went wrong on the server.", UNEXPECTED_HINTS, **ids)
