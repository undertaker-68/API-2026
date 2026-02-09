from __future__ import annotations

from datetime import datetime, timedelta, timezone, date


def iso_z(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compute_window(last_days: int, min_date_utc: str) -> tuple[datetime, datetime]:
    """
    last N days but not earlier than min_date_utc (inclusive), all UTC.
    min_date_utc format: YYYY-MM-DD
    """
    now = datetime.now(timezone.utc)
    since_by_days = now - timedelta(days=last_days)

    y, m, d = [int(x) for x in min_date_utc.split("-")]
    floor = datetime(y, m, d, tzinfo=timezone.utc)

    since = max(since_by_days, floor)
    return since, now
