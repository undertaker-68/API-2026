import logging
import requests
from app.config import Config

log = logging.getLogger("ms")

class MSClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base = cfg.ms_base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {cfg.ms_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        r = requests.get(f"{self.base}{path}", headers=self.headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        r = requests.post(f"{self.base}{path}", headers=self.headers, json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, body: dict) -> dict:
        r = requests.put(f"{self.base}{path}", headers=self.headers, json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    # --- Catalog
    def find_product_by_article(self, article: str) -> dict | None:
        res = self._get("/entity/product", params={"filter": f"article={article}"})
        rows = res.get("rows") or []
        return rows[0] if rows else None

    def find_bundle_by_article(self, article: str) -> dict | None:
        res = self._get("/entity/bundle", params={"filter": f"article={article}"})
        rows = res.get("rows") or []
        return rows[0] if rows else None

    def get_bundle_components(self, bundle_id: str) -> list[dict]:
        # /entity/bundle/{id} возвращает components
        b = self._get(f"/entity/bundle/{bundle_id}")
        return b.get("components") or []

    def get_sale_price(self, product_or_bundle: dict) -> int | None:
        # Берём дефолтную цену продажи. В МС цены обычно в "salePrices".
        prices = product_or_bundle.get("salePrices") or []
        if not prices:
            return None
        # Берём первую (обычно base sale price)
        return prices[0].get("value")

    # --- Orders
    def find_customer_order_by_name(self, name: str) -> dict | None:
        res = self._get("/entity/customerorder", params={"filter": f"name={name}"})
        rows = res.get("rows") or []
        return rows[0] if rows else None

    def get_customer_order(self, order_id: str) -> dict:
        return self._get(f"/entity/customerorder/{order_id}")

    def create_customer_order(self, body: dict) -> dict:
        return self._post("/entity/customerorder", body)

    def update_customer_order(self, order_id: str, body: dict) -> dict:
        return self._put(f"/entity/customerorder/{order_id}", body)

    def set_order_state(self, order_id: str, state_id: str) -> None:
        self._put(f"/entity/customerorder/{order_id}", {
            "state": {"meta": {"href": f"{self.base}/entity/customerorder/metadata/states/{state_id}",
                               "type": "state", "mediaType": "application/json"}}
        })

    def set_order_reserve(self, order_id: str, reserve: bool) -> None:
        self._put(f"/entity/customerorder/{order_id}", {"reserve": reserve})

    # --- Demand / Move
    def create_demand(self, body: dict) -> dict:
        return self._post("/entity/demand", body)

    def create_move(self, body: dict) -> dict:
        return self._post("/entity/move", body)
