from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv(override=False)


def _here(*parts: str) -> str:
    return os.path.join(os.path.dirname(__file__), *parts)


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


def _env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


@dataclass(frozen=True)
class Config:
    # Ozon
    ozon_client_id: str
    ozon_api_key: str
    ozon_base_url: str

    # MoySklad
    ms_token: str
    ms_base_url: str

    # throttling/retry
    ms_rps: float
    ms_retry_max: int
    ms_retry_base_seconds: float

    # Constants
    ms_org_id: str
    ms_agent_id: str
    ms_sales_channel_fbo_id: str
    ms_fbo_state_id: str

    ms_fbo_move_state_id: str
    ms_fbo_demand_state_id: str

    # Stores
    ms_fbo_move_source_store_id: str
    ms_fbo_move_target_store_id: str
    ms_fbo_demand_store_id: str

    # App
    poll_seconds: int
    dry_run: bool
    log_level: str

    # Window
    last_days: int
    min_date_utc: str  # YYYY-MM-DD

    # Paths
    state_path: str
    ms_article_cache_path: str
    log_path: str


def get_config() -> Config:
    ozon_client_id = _env_str("OZON_CLIENT_ID")
    ozon_api_key = _env_str("OZON_API_KEY")
    if not ozon_client_id or not ozon_api_key:
        raise RuntimeError("Missing OZON_CLIENT_ID / OZON_API_KEY")

    ms_token = _env_str("MS_TOKEN")
    if not ms_token:
        raise RuntimeError("Missing MS_TOKEN")

    cfg = Config(
        ozon_client_id=ozon_client_id,
        ozon_api_key=ozon_api_key,
        ozon_base_url=_env_str("OZON_BASE_URL", "https://api-seller.ozon.ru"),

        ms_token=ms_token,
        ms_base_url=_env_str("MS_BASE_URL", "https://api.moysklad.ru/api/remap/1.2"),

        ms_rps=_env_float("MS_RPS", _env_float("FBO_MS_RPS", 3.0)),
        ms_retry_max=_env_int("MS_RETRY_MAX", _env_int("FBO_MS_RETRY_MAX", 6)),
        ms_retry_base_seconds=_env_float("MS_RETRY_BASE_SECONDS", _env_float("FBO_MS_RETRY_BASE_SECONDS", 0.6)),

        ms_org_id=_env_str("MS_ORG_ID", "12d36dcd-8b6c-11e9-9109-f8fc00176e21"),
        ms_agent_id=_env_str("MS_AGENT_ID", "f61bfcf9-2d74-11ec-0a80-04c700041e03"),
        ms_sales_channel_fbo_id=_env_str("MS_SALES_CHANNEL_FBO_ID"),
        ms_fbo_state_id=_env_str("MS_FBO_STATE_ID"),

        ms_fbo_move_state_id=_env_str("MS_FBO_MOVE_STATE_ID", "b0d2c89d-5c7c-11ef-0a80-0cd4001f5885"),
        ms_fbo_demand_state_id=_env_str("MS_FBO_DEMAND_STATE_ID", "b543e330-44e4-11f0-0a80-0da5002260ab"),

        ms_fbo_move_source_store_id=_env_str("MS_FBO_MOVE_SOURCE_STORE_ID", "7cdb9b20-9910-11ec-0a80-08670002d998"),
        ms_fbo_move_target_store_id=_env_str("MS_FBO_MOVE_TARGET_STORE_ID", "77b4a517-3b82-11f0-0a80-18cb00037a24"),
        ms_fbo_demand_store_id=_env_str("MS_FBO_DEMAND_STORE_ID", "77b4a517-3b82-11f0-0a80-18cb00037a24"),

        poll_seconds=_env_int("POLL_SECONDS", 80),
        dry_run=_env_str("FBO_DRY_RUN", _env_str("DRY_RUN", "0")) == "1",
        log_level=_env_str("FBO_LOG_LEVEL", _env_str("LOG_LEVEL", "INFO")).upper(),

        last_days=_env_int("FBO_LAST_DAYS", 20),
        min_date_utc=_env_str("FBO_MIN_DATE_UTC", "2026-02-02"),

        state_path=_here("data", "fbo_state.json"),
        ms_article_cache_path=_here("data", "ms_article_cache.json"),
        log_path=_here("logs", "fbo.log"),
    )

    if not cfg.ms_sales_channel_fbo_id:
        raise RuntimeError("Missing MS_SALES_CHANNEL_FBO_ID")
    if not cfg.ms_fbo_state_id:
        raise RuntimeError("Missing MS_FBO_STATE_ID")

    return cfg
