"""Drop warning events about things that have already recovered.

Kubernetes keeps events for about an hour. Right after a deploy (or a node
start) there are many Warning events such as failed readiness probes that
were only true for a few seconds. Reporting them as live problems makes the
AI diagnose failures that no longer exist.

Rules (an event is kept unless it is clearly resolved):
- Pod events: keep only if the pod is still in the problem list now.
  A pod that is healthy, or no longer exists, has recovered.
- Node events: keep only if the node is not Ready now.
- Anything else (ReplicaSet, Service, PVC, ...): keep if seen in the last hour.
"""

from typing import Any

from loguru import logger

from app.kubernetes.executor import KubectlError, get_json
from app.models.investigation import EventsReport, PodReport

OTHER_EVENTS_MAX_AGE_MINUTES = 60


def _ready_nodes() -> set[str] | None:
    """Names of Ready nodes, or None if nodes can't be listed (then node events are kept)."""
    try:
        nodes = get_json(["get", "nodes"]).get("items", [])
    except KubectlError:
        return None
    ready = set()
    for node in nodes:
        conditions = node.get("status", {}).get("conditions", [])
        if any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
            ready.add(node.get("metadata", {}).get("name", ""))
    return ready


def drop_resolved_events(events: EventsReport, pods: PodReport, raw_pods: list[dict[str, Any]] | None) -> EventsReport:
    if raw_pods is None or events.error:
        return events  # not enough information to judge; keep everything

    problem_pods = {(p.namespace, p.name) for p in pods.problematic_pods}
    ready_nodes = _ready_nodes()

    kept = []
    for event in events.findings:
        kind, _, name = event.object.partition("/")
        if kind == "Pod":
            keep = (event.namespace, name) in problem_pods
        elif kind == "Node":
            keep = ready_nodes is None or name not in ready_nodes
        else:
            keep = event.age_minutes is None or event.age_minutes <= OTHER_EVENTS_MAX_AGE_MINUTES
        if keep:
            kept.append(event)

    dropped = len(events.findings) - len(kept)
    if dropped:
        logger.info("Events: ignored {} event group(s) about resources that have recovered", dropped)

    counts: dict[str, int] = {}
    for event in kept:
        key = event.category or event.reason
        counts[key] = counts.get(key, 0) + 1
    return events.model_copy(
        update={
            "findings": kept,
            "total_warnings": sum(1 for e in kept if e.type == "Warning"),
            "counts_by_category": counts,
            "resolved_ignored": dropped,
        }
    )
