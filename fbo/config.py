from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv(override=False)


@dataclass(frozen=True)
class Config:
    ozon_client_id: str
    ozon_api_key: str
    ozon_base_url: str = "https://api-seller.ozon.ru"

    ms_token: str = ""
    ms_base_url: str = "https://api.moysklad.ru/api/remap/1.2"

    ms_org_id: str = "12d36dcd-8b6c-11e9-9109-f8fc00176e21"
    ms_agent_id: str = "f61bfcf9-2d74-11ec-0a80-04c700041e03"

    ms_sales_channel_fbo_id: str = ""
    ms_customerorder_state_id: str = ""

    # stores
    ms_dest_store_id: str = "77b4a517-3b82-11f0-0a80-18cb00037a24"  # склад назначения (для CO и Demand)
    ms_move_source_store_id: str = "7cdb9b20-9910-11ec-0a80-08670002d998"
    ms_move_target_store_id: str = "77b4a517-3b82-11f0-0a80-18cb00037a24"

    # states
    ms_move_state_id: str = "b0d2c89d-5c7c-11ef-0a80-0cd4001f5885"
    ms_demand_state_id: str = "b543e330-44e4-11f0-0a80-0da5002260ab"

    poll_seconds: int = 80
    dry_run: bool = False
    log_level: str = "INFO"

    min_date_utc: str = "2026-02-02"
    last_days: int = 20

    state_path: str = os.path.join(os.path.dirname(__file__), "data", "fbo_state.json")
    log_path: str = os.path.join(os.path.dirname(__file__), "logs", "fbo.log")


def get_config() -> Config:
    ozon_client_id = os.getenv("OZON_CLIENT_ID", "").strip()
    ozon_api_key = os.getenv("OZON_API_KEY", "").strip()
    ms_token = os.getenv("MS_TOKEN", "").strip()
    ms_base_url = os.getenv("MS_BASE_URL", "https://api.moysklad.ru/api/remap/1.2").strip()

    ms_org_id = os.getenv("MS_FBO_ORG_ID", "12d36dcd-8b6c-11e9-9109-f8fc00176e21").strip()
    ms_agent_id = os.getenv("MS_FBO_AGENT_ID", "f61bfcf9-2d74-11ec-0a80-04c700041e03").strip()

    ms_sales_channel_fbo_id = os.getenv("MS_SALES_CHANNEL_FBO_ID", "").strip()
    ms_customerorder_state_id = os.getenv("MS_FBO_STATE_ID", "").strip()

    ms_dest_store_id = os.getenv("MS_FBO_DEST_STORE_ID", "77b4a517-3b82-11f0-0a80-18cb00037a24").strip()
    ms_move_source_store_id = os.getenv("MS_FBO_MOVE_SOURCE_STORE_ID", "7cdb9b20-9910-11ec-0a80-08670002d998").strip()
    ms_move_target_store_id = os.getenv("MS_FBO_MOVE_TARGET_STORE_ID", "77b4a517-3b82-11f0-0a80-18cb00037a24").strip()

    ms_move_state_id = os.getenv("MS_FBO_MOVE_STATE_ID", "b0d2c89d-5c7c-11ef-0a80-0cd4001f5885").strip()
    ms_demand_state_id = os.getenv("MS_FBO_DEMAND_STATE_ID", "b543e330-44e4-11f0-0a80-0da5002260ab").strip()

    poll_seconds = int(os.getenv("POLL_SECONDS", "80"))
    log_level = os.getenv("FBO_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO")).strip().upper()
    dry_run = os.getenv("FBO_DRY_RUN", "0").strip() == "1"

    if not ozon_client_id or not ozon_api_key:
        raise RuntimeError("Missing OZON_CLIENT_ID / OZON_API_KEY")
    if not ms_token:
        raise RuntimeError("Missing MS_TOKEN")
    if not ms_sales_channel_fbo_id:
        raise RuntimeError("Missing MS_SALES_CHANNEL_FBO_ID")
    if not ms_customerorder_state_id:
        raise RuntimeError("Missing MS_FBO_STATE_ID (CustomerOrder state)")

    return Config(
        ozon_client_id=ozon_client_id,
        ozon_api_key=ozon_api_key,
        ms_token=ms_token,
        ms_base_url=ms_base_url,
        ms_org_id=ms_org_id,
        ms_agent_id=ms_agent_id,
        ms_sales_channel_fbo_id=ms_sales_channel_fbo_id,
        ms_customerorder_state_id=ms_customerorder_state_id,
        ms_dest_store_id=ms_dest_store_id,
        ms_move_source_store_id=ms_move_source_store_id,
        ms_move_target_store_id=ms_move_target_store_id,
        ms_move_state_id=ms_move_state_id,
        ms_demand_state_id=ms_demand_state_id,
        poll_seconds=poll_seconds,
        dry_run=dry_run,
        log_level=log_level,
    )
