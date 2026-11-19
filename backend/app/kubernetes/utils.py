from datetime import datetime, timezone


def parse_time(value: str | None) -> datetime | None:
    """Parse a Kubernetes timestamp like '2026-11-17T10:00:00Z'."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def minutes_since(value: str | None) -> int | None:
    started = parse_time(value)
    if started is None:
        return None
    return int((datetime.now(timezone.utc) - started).total_seconds() // 60)


def shorten(text: str | None, limit: int = 300) -> str | None:
    if text is None:
        return None
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."
