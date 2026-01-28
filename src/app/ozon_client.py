import logging
from app.config import Config
from utils.http import post_json

log = logging.getLogger("ozon")

class OzonClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base = "https://api-seller.ozon.ru"
        self.headers = {
            "Client-Id": cfg.ozon_client_id,
            "Api-Key": cfg.ozon_api_key,
            "Content-Type": "application/json",
        }

    def unfulfilled_list(self, cutoff_from: str, cutoff_to: str, status: str | None, limit: int = 50, offset: int = 0) -> dict:
        url = f"{self.base}/v3/posting/fbs/unfulfilled/list"
        payload: dict = {
            "filter": {
                "cutoff_from": cutoff_from,
                "cutoff_to": cutoff_to,
            },
            "limit": limit,
            "offset": offset,
            "with": {
                "analytics_data": False,
                "barcodes": False,
                "financial_data": False,
                "translit": True,
            },
        }
        if status:
            payload["filter"]["status"] = status
        return post_json(url, self.headers, payload)

    def get_posting(self, posting_number: str) -> dict:
        url = f"{self.base}/v3/posting/fbs/get"
        payload = {"posting_number": posting_number, "with": {"analytics_data": True, "financial_data": False}}
        return post_json(url, self.headers, payload)
