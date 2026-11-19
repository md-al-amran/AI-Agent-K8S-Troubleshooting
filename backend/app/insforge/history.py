"""Save investigation history and progress to InsForge.

One row in the `investigations` table per run. The row is created when the
investigation starts and updated after every step. A database trigger
publishes each change on the realtime channel `investigations:<user_id>`,
which is how the dashboard shows live progress.

Writing history is best-effort: if InsForge is down, the investigation still
runs and returns its result. Writes use the user's own token, so Row Level
Security applies.
"""

from typing import Any

import httpx
from loguru import logger

from app.core.config import get_settings
from app.models.diagnosis import Diagnosis
from app.models.investigation import Investigation

# Progress steps, in order. The frontend shows the same list.
STEPS = ["pods", "logs", "events", "deployments", "network", "ai"]

TABLE_PATH = "/api/database/records/investigations"


class InvestigationHistory:
    def __init__(self, token: str) -> None:
        settings = get_settings()
        self.id: str | None = None
        self._finished = False
        self._client = httpx.Client(
            base_url=settings.insforge_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.insforge_timeout_seconds,
        )

    # ---- writes ----

    def start(self, cluster: str | None = None) -> str | None:
        """Create the history row. Returns its id (None if InsForge could not save it)."""
        try:
            response = self._client.post(
                TABLE_PATH,
                json=[{"status": "running", "current_step": STEPS[0], "steps": [], "cluster": cluster}],
                headers={"Prefer": "return=representation"},
            )
            response.raise_for_status()
            self.id = response.json()[0]["id"]
            logger.info("Investigation {} started", self.id)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            logger.warning("Could not save investigation history: {}", _describe(exc))
        return self.id

    def step(self, name: str) -> None:
        """Mark `name` as running and every earlier step as done."""
        done = STEPS[: STEPS.index(name)] if name in STEPS else []
        self._update({"current_step": name, "steps": done})

    def finish(
        self,
        status: str,
        investigation: Investigation | None = None,
        diagnosis: Diagnosis | None = None,
        error: str | None = None,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        fields: dict[str, Any] = {"status": status, "current_step": None, "error": error}

        if investigation is not None:
            failed = set(investigation.summary.failed_steps)
            fields["steps"] = [s for s in STEPS if s not in failed and (s != "ai" or diagnosis is not None)]
            fields["namespace"] = _namespace(diagnosis, investigation)

        if diagnosis is not None:
            fields.update(
                title=diagnosis.title or ("Healthy" if diagnosis.healthy else None),
                root_cause=diagnosis.root_cause,
                severity=diagnosis.severity,
                confidence=diagnosis.confidence,
                diagnosis=diagnosis.model_dump(mode="json"),
            )
        elif investigation is not None:
            # No AI answer: use the main pod problem as the title, e.g. "CrashLoopBackOff".
            pods = investigation.pods.problematic_pods
            fields["title"] = pods[0].status if pods else "No AI diagnosis"

        self._update(fields)
        self._client.close()

    # ---- helpers ----

    def _update(self, fields: dict[str, Any]) -> None:
        if self.id is None:
            return
        try:
            self._client.patch(TABLE_PATH, params={"id": f"eq.{self.id}"}, json=fields).raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Could not update investigation {}: {}", self.id, _describe(exc))


def _namespace(diagnosis: Diagnosis | None, investigation: Investigation) -> str | None:
    """Namespace of the main issue: from 'Kind/namespace/name', else from the failing pods."""
    if diagnosis is not None:
        for resource in diagnosis.affected_resources:
            parts = resource.split("/")
            if len(parts) == 3:
                return parts[1]
    namespaces = sorted({p.namespace for p in investigation.pods.problematic_pods})
    return ", ".join(namespaces[:3]) or None


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
    return exc.__class__.__name__
