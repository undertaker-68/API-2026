from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv(override=False)


@dataclass(frozen=True)
class Config:
    # Ozon
    ozon_client_id: str
    ozon_api_key: str
    ozon_base_url: str = "https://api-seller.ozon.ru"

    # MoySklad
    ms_token: str = ""
    ms_base_url: str = "https://api.moysklad.ru/api/remap/1.2"

    ms_org_id: str = "12d36dcd-8b6c-11e9-9109-f8fc00176e21"
    ms_agent_id: str = "f61bfcf9-2d74-11ec-0a80-04c700041e03"

    ms_sales_channel_fbo_id: str = ""
    ms_fbo_state_id: str = ""

    # Move/Demand states + stores
    ms_fbo_move_state_id: str = ""
    ms_fbo_demand_state_id: str = ""

    ms_fbo_move_source_store_id: str = ""
    ms_fbo_move_target_store_id: str = ""
    ms_fbo_demand_store_id: str = ""

    # Runtime
    poll_seconds: int = 80
    dry_run: bool = False
    log_level: str = "INFO"

    # Window
    min_date_utc: str = "2026-02-02"
    last_days: int = 20

    # MS rate limit/retry
    ms_rps: float = 4.0
    ms_retry_max: int = 6
    ms_retry_base_seconds: float = 0.6

    # Paths
    state_path: str = os.path.join(os.path.dirname(__file__), "data", "fbo_state.json")
    log_path: str = os.path.join(os.path.dirname(__file__), "logs", "fbo.log")
    ms_article_cache_path: str = os.path.join(os.path.dirname(__file__), "data", "ms_article_cache.json")


def get_config() -> Config:
    ozon_client_id = os.getenv("OZON_CLIENT_ID", "").strip()
    ozon_api_key = os.getenv("OZON_API_KEY", "").strip()

    ms_token = os.getenv("MS_TOKEN", "").strip()
    ms_base_url = os.getenv("MS_BASE_URL", "https://api.moysklad.ru/api/remap/1.2").strip()

    ms_org_id = os.getenv("MS_FBO_ORG_ID", "12d36dcd-8b6c-11e9-9109-f8fc00176e21").strip()
    ms_agent_id = os.getenv("MS_FBO_AGENT_ID", "f61bfcf9-2d74-11ec-0a80-04c700041e03").strip()

    ms_sales_channel_fbo_id = os.getenv("MS_SALES_CHANNEL_FBO_ID", "").strip()
    ms_fbo_state_id = os.getenv("MS_FBO_STATE_ID", "").strip()

    ms_fbo_move_state_id = os.getenv("MS_FBO_MOVE_STATE_ID", "").strip()
    ms_fbo_demand_state_id = os.getenv("MS_FBO_DEMAND_STATE_ID", "").strip()

    ms_fbo_move_source_store_id = os.getenv("MS_FBO_MOVE_SOURCE_STORE_ID", "").strip()
    ms_fbo_move_target_store_id = os.getenv("MS_FBO_MOVE_TARGET_STORE_ID", "").strip()
    ms_fbo_demand_store_id = os.getenv("MS_FBO_DEMAND_STORE_ID", "").strip()

    poll_seconds = int(os.getenv("POLL_SECONDS", "80"))
    log_level = os.getenv("FBO_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO")).strip().upper()
    dry_run = os.getenv("FBO_DRY_RUN", "0").strip() == "1"

    ms_rps = float(os.getenv("MS_RPS", "4"))
    ms_retry_max = int(os.getenv("MS_RETRY_MAX", "6"))
    ms_retry_base_seconds = float(os.getenv("MS_RETRY_BASE_SECONDS", "0.6"))

    if not ozon_client_id or not ozon_api_key:
        raise RuntimeError("Missing OZON_CLIENT_ID / OZON_API_KEY")
    if not ms_token:
        raise RuntimeError("Missing MS_TOKEN")
    if not ms_sales_channel_fbo_id:
        raise RuntimeError("Missing MS_SALES_CHANNEL_FBO_ID")
    if not ms_fbo_state_id:
        raise RuntimeError("Missing MS_FBO_STATE_ID")

    for k, v in [
        ("MS_FBO_MOVE_STATE_ID", ms_fbo_move_state_id),
        ("MS_FBO_DEMAND_STATE_ID", ms_fbo_demand_state_id),
        ("MS_FBO_MOVE_SOURCE_STORE_ID", ms_fbo_move_source_store_id),
        ("MS_FBO_MOVE_TARGET_STORE_ID", ms_fbo_move_target_store_id),
        ("MS_FBO_DEMAND_STORE_ID", ms_fbo_demand_store_id),
    ]:
        if not v:
            raise RuntimeError(f"Missing {k}")

    return Config(
        ozon_client_id=ozon_client_id,
        ozon_api_key=ozon_api_key,
        ms_token=ms_token,
        ms_base_url=ms_base_url,
        ms_org_id=ms_org_id,
        ms_agent_id=ms_agent_id,
        ms_sales_channel_fbo_id=ms_sales_channel_fbo_id,
        ms_fbo_state_id=ms_fbo_state_id,
        ms_fbo_move_state_id=ms_fbo_move_state_id,
        ms_fbo_demand_state_id=ms_fbo_demand_state_id,
        ms_fbo_move_source_store_id=ms_fbo_move_source_store_id,
        ms_fbo_move_target_store_id=ms_fbo_move_target_store_id,
        ms_fbo_demand_store_id=ms_fbo_demand_store_id,
        poll_seconds=poll_seconds,
        dry_run=dry_run,
        log_level=log_level,
        ms_rps=ms_rps,
        ms_retry_max=ms_retry_max,
        ms_retry_base_seconds=ms_retry_base_seconds,
    )
