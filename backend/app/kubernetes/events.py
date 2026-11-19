"""Events Analyzer: summarize Warning events across the cluster.

Source: kubectl get events -A -o json
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.kubernetes.executor import get_json
from app.kubernetes.utils import parse_time, shorten
from app.models.investigation import EventFinding, EventsReport

MAX_FINDINGS = 50

# Event reasons we want to call out, mapped to a clear category name.
CATEGORY_BY_REASON = {
    "FailedScheduling": "FailedScheduling",
    "BackOff": "BackOff",
    "FailedMount": "FailedMount",
    "FailedAttachVolume": "FailedMount",
    "ErrImagePull": "ErrImagePull",
    "ImagePullBackOff": "ErrImagePull",
    "Unhealthy": "Unhealthy",
    "FailedCreate": "FailedCreate",
    "Evicted": "Evicted",
    "OOMKilling": "OOMKilled",
    "NodeNotReady": "NodeNotReady",
    "FailedCreatePodSandBox": "FailedCreatePodSandBox",
}


def _category(reason: str, message: str) -> str | None:
    # Image pull failures are reported with the generic reason "Failed".
    if reason == "Failed" and "pull" in message.lower():
        return "FailedPull"
    return CATEGORY_BY_REASON.get(reason)


def _last_seen(event: dict[str, Any]) -> datetime | None:
    series = event.get("series") or {}
    return (
        parse_time(series.get("lastObservedTime"))
        or parse_time(event.get("lastTimestamp"))
        or parse_time(event.get("eventTime"))
        or parse_time(event.get("metadata", {}).get("creationTimestamp"))
    )


def analyze_events() -> EventsReport:
    """Group Warning events by object and reason, newest first."""
    events = get_json(["get", "events", "-A"]).get("items", [])
    grouped: dict[tuple[str, str, str], EventFinding] = {}

    for event in events:
        reason = event.get("reason") or "Unknown"
        message = event.get("message") or ""
        category = _category(reason, message)
        if event.get("type") != "Warning" and category is None:
            continue

        involved = event.get("involvedObject") or {}
        namespace = involved.get("namespace") or event.get("metadata", {}).get("namespace") or ""
        obj = f"{involved.get('kind', '?')}/{involved.get('name', '?')}"
        count = (event.get("series") or {}).get("count") or event.get("count") or 1
        last_seen = _last_seen(event)
        age = int((datetime.now(timezone.utc) - last_seen).total_seconds() // 60) if last_seen else None

        key = (namespace, obj, reason)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = EventFinding(
                namespace=namespace,
                object=obj,
                reason=reason,
                category=category,
                type=event.get("type") or "Normal",
                message=shorten(message) or "",
                count=count,
                last_seen=last_seen,
                age_minutes=age,
            )
            continue

        # Same object and reason seen again: add up the count, keep the newest message.
        existing.count += count
        if last_seen and (existing.last_seen is None or last_seen > existing.last_seen):
            existing.last_seen = last_seen
            existing.age_minutes = age
            existing.message = shorten(message) or ""

    oldest = datetime.min.replace(tzinfo=timezone.utc)
    findings = sorted(grouped.values(), key=lambda f: f.last_seen or oldest, reverse=True)
    counts = Counter(f.category or f.reason for f in findings)
    warnings = sum(1 for f in findings if f.type == "Warning")

    logger.info("Events analyzer: {} events, {} warning groups", len(events), warnings)
    return EventsReport(
        total_warnings=warnings,
        counts_by_category=dict(counts.most_common()),
        findings=findings[:MAX_FINDINGS],
    )
