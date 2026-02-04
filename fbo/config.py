from datetime import date

# ===== МойСклад =====
MS_BASE_URL = "https://api.moysklad.ru/api/remap/1.2"
MS_TOKEN = "7349ecbbcbc6fc07f7c2238f6822aed63f4ddb12"

ORGANIZATION_ID = "12d36dcd-8b6c-11e9-9109-f8fc00176e21"
AGENT_ID = "f61bfcf9-2d74-11ec-0a80-04c700041e03"
SALES_CHANNEL_FBO_ID = "fe931ffb-9fd0-11ee-0a80-0274000ebbdc"
STATE_FBO_ID = "921c872f-d54e-11ef-0a80-1823001350aa"

# фиксированный склад (обязателен)
STORE_ID = "42db7535-5bb6-11ef-0a80-1589000daaa3"

MS_HEADERS = {
    "Authorization": f"Bearer {MS_TOKEN}",
    "Accept": "application/json;charset=utf-8",
    "Content-Type": "application/json",
}

# ===== Ozon =====
OZON_BASE_URL = "https://api-seller.ozon.ru"
OZON_CLIENT_ID = "<CLIENT_ID>"
OZON_API_KEY = "<API_KEY>"

OZON_HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json",
}

# ===== Ограничения =====
MIN_CREATED_DATE = date(2026, 2, 2)
DAYS_BACK = 10

# ===== Runtime =====
DRY_RUN = True          # ← для боя поставить False
LOG_LEVEL = "DEBUG"

OZON_FBO_MARK = "ozon_fbo"
