from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

CUTOFF_DATE = datetime(2026, 2, 2, 0, 0, 0, tzinfo=timezone.utc)
WINDOW_DAYS = 10
POLL_SECONDS = 80

# MS stores
STORE_MAIN_ID = "7cdb9b20-9910-11ec-0a80-08670002d998"
STORE_FBO_ID  = "77b4a517-3b82-11f0-0a80-18cb00037a24"

# MS states
MOVE_STATE_ID   = "b0d2c89d-5c7c-11ef-0a80-0cd4001f5885"
DEMAND_STATE_ID = "b543e330-44e4-11f0-0a80-0da5002260ab"

# Ozon list enum states
STATE_READY_TO_SUPPLY = 2
STATE_CANCELLED = 10

@dataclass(frozen=True)
class SyncWindow:
    since: datetime
    to: datetime

def calc_window(now_utc: datetime) -> SyncWindow:
    since = max(CUTOFF_DATE, now_utc - timedelta(days=WINDOW_DAYS))
    return SyncWindow(since=since, to=now_utc)
