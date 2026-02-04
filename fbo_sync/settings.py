from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


# polling
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "80"))

# ваши склады
STORE_MAIN_ID = os.getenv("STORE_MAIN_ID", "7cdb9b20-9910-11ec-0a80-08670002d998")  # пример
STORE_FBO_ID = os.getenv("STORE_FBO_ID", "77b4a517-3b82-11f0-0a80-18cb00037a24")   # пример (FBO)

# статусы move/demand (если надо)
MOVE_STATE_ID = os.getenv("MOVE_STATE_ID", "")
DEMAND_STATE_ID = os.getenv("DEMAND_STATE_ID", "")

# статусы OzON
STATE_READY_TO_SUPPLY = "READY_TO_SUPPLY"
STATE_CANCELLED = "CANCELLED"


def calc_window(now_utc: datetime, hours_back: int = 48) -> tuple[str, str]:
    """
    Окно выборки поставок из Ozon.
    """
    to_dt = now_utc.astimezone(timezone.utc)
    since_dt = to_dt - timedelta(hours=hours_back)
    # Ozon ждёт Z
    def iso(dt: datetime) -> str:
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return iso(since_dt), iso(to_dt)


@dataclass(frozen=True)
class Settings:
    # Ozon
    ozon_client_id: str
    ozon_api_key: str

    # MS
    ms_token: str
    ms_base_url: str
    org_id: str
    agent_id: str

    # канал продаж
    sales_channel_id: str

    # статус CustomerOrder (ВАЖНО!)
    customerorder_state_id: str

    dry_run: bool = False

    @staticmethod
    def _must(k: str) -> str:
        v = os.getenv(k)
        if not v:
            raise RuntimeError(f"Missing env {k}")
        return v

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            ozon_client_id=cls._must("OZON_CLIENT_ID"),
            ozon_api_key=cls._must("OZON_API_KEY"),
            ms_token=cls._must("MS_TOKEN"),
            ms_base_url=os.getenv("MS_BASE_URL", "https://api.moysklad.ru/api/remap/1.2"),
            org_id=cls._must("MS_ORG_ID"),
            agent_id=cls._must("MS_AGENT_ID"),
            # ВАЖНО: отдельная переменная для FBO (чтобы не мешать FBS)
            sales_channel_id=os.getenv("MS_SALES_CHANNEL_ID_FBO") or cls._must("MS_SALES_CHANNEL_ID"),
            # отдельный статус для FBO
            customerorder_state_id=os.getenv("MS_CUSTOMERORDER_STATE_ID_FBO", ""),
            dry_run=os.getenv("DRY_RUN", "0") == "1",
        )
