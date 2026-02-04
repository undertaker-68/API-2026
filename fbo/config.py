import os
from datetime import date

# ===== МойСклад =====
MS_BASE_URL = os.getenv("MS_BASE_URL", "https://api.moysklad.ru/api/remap/1.2")
MS_TOKEN = os.environ["MS_TOKEN"].strip()

ORGANIZATION_ID = os.getenv("MS_ORG_ID", "12d36dcd-8b6c-11e9-9109-f8fc00176e21")
AGENT_ID = os.getenv("MS_AGENT_ID", "f61bfcf9-2d74-11ec-0a80-04c700041e03")
SALES_CHANNEL_FBO_ID = os.environ["MS_SALES_CHANNEL_FBO_ID"].strip()
STATE_FBO_ID = os.environ["MS_FBO_STATE_ID"].strip()

STORE_ID = os.getenv("MS_FBO_STORE_ID", "42db7535-5bb6-11ef-0a80-1589000daaa3")

MS_HEADERS = {
    "Authorization": f"Bearer {MS_TOKEN}",
    "Accept": "application/json;charset=utf-8",
    "Content-Type": "application/json",
}

# ===== Ozon =====
OZON_BASE_URL = os.getenv("OZON_BASE_URL", "https://api-seller.ozon.ru")
OZON_CLIENT_ID = os.environ["OZON_CLIENT_ID"].strip()
OZON_API_KEY = os.environ["OZON_API_KEY"].strip()

OZON_HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json",
}

# ===== Ограничения =====
MIN_CREATED_DATE = date(2026, 2, 2)
DAYS_BACK = 10

# ===== Runtime =====
DRY_RUN = os.getenv("FBO_DRY_RUN", "1").strip() not in ("0", "false", "False")
LOG_LEVEL = os.getenv("FBO_LOG_LEVEL", "DEBUG").strip()

OZON_FBO_MARK = "ozon_fbo"
