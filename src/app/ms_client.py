import logging
import requests
from app.config import Config

log = logging.getLogger("ms")


class MSClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base = cfg.ms_base_url.rstrip("/")
        # MoySklad строго требует Accept = application/json;charset=utf-8
        self.headers = {
            "Authorization": f"Bearer {cfg.ms_token}",
            "Accept": "application/json;charset=utf-8",
            "Content-Type": "application/json;charset=utf-8",
        }

    # --- low-level http with error body logging
    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        try:
            r = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                json=body,
                timeout=30,
            )
        except Exception as e:
            log.error("MS %s %s network error: %s", method, path, e)
            raise

        if r.status_code >= 400:
            log.error(
                "MS %s %s failed: %s %s | params=%s | body_keys=%s",
                method,
                path,
                r.status_code,
                r.text,
                params,
                list(body.keys()) if isinstance(body, dict) else None,
            )
            raise requests.HTTPError(f"{r.status_code} {r.text}", response=r)

        if not r.text:
            return {}
        return r.json()

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, body=body)

    def _put(self, path: str, body: dict) -> dict:
        return self._request("PUT", path, body=body)

    # --- Catalog (assortment-based)

    def find_assortment_by_article(self, article: str):
        """
        Надёжно: ищем по /entity/assortment?search=... и делаем exact match по article.
        Возвращает row (product/bundle/variant).
        """
        target = str(article).strip()
        if not target:
            return None

        res = self._get("/entity/assortment", params={"search": target, "limit": 100})
        rows = res.get("rows") or []
        for r in rows:
            if str(r.get("article") or "").strip() == target:
                return r
        return None

    def find_product_by_article(self, article: str):
        row = self.find_assortment_by_article(article)
        if not row:
            return None
        meta = (row.get("meta") or {})
        return row if meta.get("type") == "product" else None

    def find_bundle_by_article(self, article: str):
        row = self.find_assortment_by_article(article)
        if not row:
            return None
        meta = (row.get("meta") or {})
        return row if meta.get("type") == "bundle" else None

    def get_bundle_components(self, bundle_id: str) -> list[dict]:
        b = self._get(f"/entity/bundle/{bundle_id}")
        return b.get("components") or []

    def get_sale_price(self, product_or_bundle: dict) -> int | None:
        prices = product_or_bundle.get("salePrices") or []
        if not prices:
            return None
        return prices[0].get("value")

    # --- Orders

    def find_customer_order_by_name(self, name: str):
        """
        Надёжно: search + exact match по name (filter=name часто ломается).
        """
        target = str(name).strip()
        if not target:
            return None
        res = self._get("/entity/customerorder", params={"search": target, "limit": 100})
        for r in (res.get("rows") or []):
            if str(r.get("name") or "").strip() == target:
                return {"id": r.get("id")}
        return None

    def get_customer_order(self, order_id: str) -> dict:
        return self._get(f"/entity/customerorder/{order_id}")

    def create_customer_order(self, body: dict) -> dict:
        return self._post("/entity/customerorder", body)

    def update_customer_order(self, order_id: str, body: dict) -> dict:
        return self._put(f"/entity/customerorder/{order_id}", body)

    def set_order_state(self, order_id: str, state_id: str) -> None:
        self._put(
            f"/entity/customerorder/{order_id}",
            {
                "state": {
                    "meta": {
                        "href": f"{self.base}/entity/customerorder/metadata/states/{state_id}",
                        "type": "state",
                        "mediaType": "application/json",
                    }
                }
            },
        )

    def set_order_reserve(self, order_id: str, reserve: bool) -> None:
        self._put(f"/entity/customerorder/{order_id}", {"reserve": reserve})

    # --- Demand / Move
    def create_demand(self, body: dict) -> dict:
        return self._post("/entity/demand", body)

    def create_move(self, body: dict) -> dict:
        return self._post("/entity/move", body)
