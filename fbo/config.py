from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(override=False)


def _here(*parts: str) -> str:
    return os.path.join(os.path.dirname(__file__), *parts)


@dataclass(frozen=True)
class Config:
    # Ozon
    ozon_client_id: str
    ozon_api_key: str
    ozon_base_url: str = "https://api-seller.ozon.ru"

    # MoySklad
    ms_token: str = ""
    ms_base_url: str = "https://api.moysklad.ru/api/remap/1.2"

    # MS throttling/retry (runner.py ожидает эти поля)
    ms_rps: int = 3
    ms_retry_max: int = 5
    ms_retry_base_seconds: float = 0.6

    # FBO constants
    ms_org_id: str = "12d36dcd-8b6c-11e9-9109-f8fc00176e21"
    ms_agent_id: str = "f61bfcf9-2d74-11ec-0a80-04c700041e03"
    ms_sales_channel_fbo_id: str = ""
    ms_fbo_state_id: str = ""  # CustomerOrder state

    # Stores
    ms_fbo_demand_store_id: str = "77b4a517-3b82-11f0-0a80-18cb00037a24"

    # Move stores
    ms_fbo_move_source_store_id: str = "7cdb9b20-9910-11ec-0a80-08670002d998"
    ms_fbo_move_target_store_id: str = "77b4a517-3b82-11f0-0a80-18cb00037a24"

    # States
    ms_fbo_move_state_id: str = "b0d2c89d-5c7c-11ef-0a80-0cd4001f5885"
    ms_fbo_demand_state_id: str = "b543e330-44e4-11f0-0a80-0da5002260ab"

    # App
    poll_seconds: int = 80
    dry_run: bool = False
    log_level: str = "INFO"

    # Sync window
    last_days: int = 20
    min_date_utc: datetime = datetime(2026, 2, 2, tzinfo=timezone.utc)

    # Paths (main.py ожидает log_path)
    state_path: str = _here("data", "fbo_state.json")
    ms_article_cache_path: str = _here("data", "ms_article_cache.json")
    log_path: str = _here("logs", "fbo.log")


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return int(v.strip())


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return float(v.strip())


def get_config() -> Config:
    ozon_client_id = os.getenv("OZON_CLIENT_ID", "").strip()
    ozon_api_key = os.getenv("OZON_API_KEY", "").strip()
    if not ozon_client_id or not ozon_api_key:
        raise RuntimeError("Missing OZON_CLIENT_ID / OZON_API_KEY")

    ms_token = os.getenv("MS_TOKEN", "").strip()
    if not ms_token:
        raise RuntimeError("Missing MS_TOKEN")

    ms_base_url = os.getenv("MS_BASE_URL", "https://api.moysklad.ru/api/remap/1.2").strip()

    # MS throttling/retry
    ms_rps = _env_int("MS_RPS", _env_int("FBO_MS_RPS", 3))
    ms_retry_max = _env_int("MS_RETRY_MAX", _env_int("FBO_MS_RETRY_MAX", 5))
    ms_retry_base_seconds = _env_float("MS_RETRY_BASE_SECONDS", _env_float("FBO_MS_RETRY_BASE_SECONDS", 0.6))

    # ids
    ms_org_id = os.getenv("MS_FBO_ORG_ID", os.getenv("MS_ORG_ID", "12d36dcd-8b6c-11e9-9109-f8fc00176e21")).strip()
    ms_agent_id = os.getenv("MS_FBO_AGENT_ID", os.getenv("MS_AGENT_ID", "f61bfcf9-2d74-11ec-0a80-04c700041e03")).strip()
    ms_sales_channel_fbo_id = os.getenv("MS_SALES_CHANNEL_FBO_ID", "").strip()
    ms_fbo_state_id = os.getenv("MS_FBO_STATE_ID", "").strip()

    if not ms_sales_channel_fbo_id:
        raise RuntimeError("Missing MS_SALES_CHANNEL_FBO_ID")
    if not ms_fbo_state_id:
        raise RuntimeError("Missing MS_FBO_STATE_ID")

    # stores/states
    ms_fbo_demand_store_id = os.getenv("MS_FBO_DEMAND_STORE_ID", "77b4a517-3b82-11f0-0a80-18cb00037a24").strip()
    ms_fbo_move_source_store_id = os.getenv("MS_FBO_MOVE_SOURCE_STORE_ID", "7cdb9b20-9910-11ec-0a80-08670002d998").strip()
    ms_fbo_move_target_store_id = os.getenv("MS_FBO_MOVE_TARGET_STORE_ID", "77b4a517-3b82-11f0-0a80-18cb00037a24").strip()

    ms_fbo_move_state_id = os.getenv("MS_FBO_MOVE_STATE_ID", "b0d2c89d-5c7c-11ef-0a80-0cd4001f5885").strip()
    ms_fbo_demand_state_id = os.getenv("MS_FBO_DEMAND_STATE_ID", "b543e330-44e4-11f0-0a80-0da5002260ab").strip()

    poll_seconds = _env_int("POLL_SECONDS", 80)
    dry_run = os.getenv("FBO_DRY_RUN", os.getenv("DRY_RUN", "0")).strip() == "1"
    log_level = os.getenv("FBO_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO")).strip().upper()

    last_days = _env_int("FBO_LAST_DAYS", 20)
    min_date_utc = datetime(2026, 2, 2, tzinfo=timezone.utc)

    return Config(
        ozon_client_id=ozon_client_id,
        ozon_api_key=ozon_api_key,
        ms_token=ms_token,
        ms_base_url=ms_base_url,
        ms_rps=ms_rps,
        ms_retry_max=ms_retry_max,
        ms_retry_base_seconds=ms_retry_base_seconds,
        ms_org_id=ms_org_id,
        ms_agent_id=ms_agent_id,
        ms_sales_channel_fbo_id=ms_sales_channel_fbo_id,
        ms_fbo_state_id=ms_fbo_state_id,
        ms_fbo_demand_store_id=ms_fbo_demand_store_id,
        ms_fbo_move_source_store_id=ms_fbo_move_source_store_id,
        ms_fbo_move_target_store_id=ms_fbo_move_target_store_id,
        ms_fbo_move_state_id=ms_fbo_move_state_id,
        ms_fbo_demand_state_id=ms_fbo_demand_state_id,
        poll_seconds=poll_seconds,
        dry_run=dry_run,
        log_level=log_level,
        last_days=last_days,
        min_date_utc=min_date_utc,
    )
