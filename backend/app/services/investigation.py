"""Investigation Service: run every inspector in order and combine the evidence.

Flow: check pods -> collect logs -> analyze events -> inspect deployments -> check networking

If one step fails, it records the error in its own report and the rest still run.
Only an unreachable cluster stops the whole investigation (KubectlError).
"""

import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from loguru import logger
from pydantic import BaseModel

from app.kubernetes.correlate import drop_resolved_events
from app.kubernetes.deployments import inspect_deployments
from app.kubernetes.events import analyze_events
from app.kubernetes.executor import check_cluster_access
from app.kubernetes.logs import collect_logs
from app.kubernetes.network import inspect_network
from app.kubernetes.pods import fetch_pods, inspect_pods
from app.models.investigation import (
    DeploymentsReport,
    EventsReport,
    Investigation,
    InvestigationSummary,
    LogsReport,
    NetworkReport,
    PodReport,
)

Report = TypeVar("Report", bound=BaseModel)


def _run_step(
    name: str,
    report_type: type[Report],
    step: Callable[[], Report],
    failed: list[str],
    on_step: Callable[[str], None] | None = None,
) -> Report:
    if on_step is not None:
        on_step(name)
    try:
        return step()
    except Exception as exc:  # one broken step must not hide the evidence from the others
        logger.exception("Investigation step '{}' failed", name)
        failed.append(name)
        return report_type(error=str(exc))


def investigate_cluster(
    on_step: Callable[[str], None] | None = None,
    cluster_name: str = "the cluster",
) -> Investigation:
    """Collect evidence from the cluster.

    `on_step` (optional) is called with each step name ("pods", "logs", ...)
    just before that step runs, so callers can report progress.
    `cluster_name` is only used in error messages. Pick the cluster with
    `executor.use_cluster(...)` around this call.
    """
    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    logger.info("Investigation started")

    check_cluster_access(cluster_name)

    failed: list[str] = []
    raw_pods: list[dict[str, Any]] | None = None

    def pods_step() -> PodReport:
        nonlocal raw_pods
        raw_pods = fetch_pods()
        return inspect_pods(raw_pods)

    pods = _run_step("pods", PodReport, pods_step, failed, on_step)
    logs = _run_step("logs", LogsReport, lambda: collect_logs(pods.problematic_pods), failed, on_step)
    events = _run_step(
        "events", EventsReport, lambda: drop_resolved_events(analyze_events(), pods, raw_pods), failed, on_step
    )
    deployments = _run_step("deployments", DeploymentsReport, inspect_deployments, failed, on_step)
    network = _run_step("network", NetworkReport, lambda: inspect_network(raw_pods), failed, on_step)

    summary = InvestigationSummary(
        healthy=pods.healthy and deployments.healthy and network.healthy and not failed,
        problematic_pods=len(pods.problematic_pods),
        warning_events=events.total_warnings,
        unhealthy_deployments=len(deployments.unhealthy_deployments),
        network_issues=len(network.service_issues) + len(network.dns.issues),
        failed_steps=failed,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info("Investigation finished in {}ms: {}", duration_ms, summary.model_dump())

    return Investigation(
        started_at=started_at,
        duration_ms=duration_ms,
        summary=summary,
        pods=pods,
        logs=logs,
        events=events,
        deployments=deployments,
        network=network,
    )
