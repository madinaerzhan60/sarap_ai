from datetime import datetime, timedelta, timezone


def next_poll(activity: str, critical_found: bool = False, failures: int = 0) -> datetime:
    """Adaptive near-real-time schedule with simple failure backoff."""
    base_minutes = {"high": 7, "medium": 20, "low": 45}.get(activity, 30)
    if critical_found:
        base_minutes = 5
    base_minutes = min(180, base_minutes * (2 ** min(failures, 3)))
    return datetime.now(timezone.utc) + timedelta(minutes=base_minutes)
