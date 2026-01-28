from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Config:
    # Ozon
    ozon_client_id: str
    ozon_api_key: str

    # MoySklad
    ms_token: str
    ms_base_url: str = "https://api.moysklad.ru/api/remap/1.2"

    # Fixed IDs (твои)
    org_id: str = "12d36dcd-8b6c-11e9-9109-f8fc00176e21"
    agent_id: str = "f61bfcf9-2d74-11ec-0a80-04c700041e03"
    sales_channel_id: str = "fede2826-9fd0-11ee-0a80-0641000f3d25"

    store_ozon_id: str = "42db7535-5bb6-11ef-0a80-1589000daaa3"
    store_main_id: str = "7cdb9b20-9910-11ec-0a80-08670002d998"

    # Runtime
    dry_run: bool = False
    poll_seconds: int = 300

def load_config() -> Config:
    dry = os.environ.get("DRY_RUN", "0").strip() in ("1", "true", "TRUE", "yes", "YES")
    return Config(
        ozon_client_id=os.environ["OZON_CLIENT_ID"].strip(),
        ozon_api_key=os.environ["OZON_API_KEY"].strip(),
        ms_token=os.environ["MS_TOKEN"].strip(),
        ms_base_url=os.environ.get("MS_BASE_URL", "https://api.moysklad.ru/api/remap/1.2").strip(),
        dry_run=dry,
        poll_seconds=int(os.environ.get("POLL_SECONDS", "300")),
    )
