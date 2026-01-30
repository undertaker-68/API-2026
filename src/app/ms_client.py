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

    # ---------------------------
    # Catalog: exact by article
    # ---------------------------

    @staticmethod
    def _first_row(res: dict) -> dict | None:
        rows = res.get("rows") or []
        return rows[0] if rows else None

    def find_bundle_by_article_exact(self, article: str) -> dict | None:
        a = str(article).strip()
        if not a:
            return None
        res = self._get("/entity/bundle", params={"filter": f"article={a}", "limit": 1})
        return self._first_row(res)

    def find_product_by_article_exact(self, article: str) -> dict | None:
        a = str(article).strip()
        if not a:
            return None
        res = self._get("/entity/product", params={"filter": f"article={a}", "limit": 1})
        return self._first_row(res)

    def find_variant_by_article_exact(self, article: str) -> dict | None:
        a = str(article).strip()
        if not a:
            return None
        res = self._get("/entity/variant", params={"filter": f"article={a}", "limit": 1})
        return self._first_row(res)

    # ---------------------------
    # Catalog: fallback assortment search + exact article
    # ---------------------------

    def find_assortment_by_article_search_exact(self, article: str) -> dict | None:
        """
        Надёжно в реальной жизни: /entity/assortment?search=... + exact match по article.
        """
        target = str(article).strip()
        if not target:
            return None

        res = self._get("/entity/assortment", params={"search": target, "limit": 100})
        for r in (res.get("rows") or []):
            if str(r.get("article") or "").strip() == target:
                return r
        return None

    def get_bundle_components(self, bundle_id: str) -> list[dict]:
        b = self._get(f"/entity/bundle/{bundle_id}", params={"expand": "components.assortment"})
        comps = b.get("components") or {}
        rows = comps.get("rows") if isinstance(comps, dict) else None
        return rows or []

    def get_by_meta_href(self, href: str) -> dict:
        # meta.href полный URL — делаем GET напрямую
        r = requests.get(href, headers=self.headers, timeout=30)
        if r.status_code >= 400:
            log.error("MS GET meta href failed: %s %s", r.status_code, r.text)
            raise requests.HTTPError(f"{r.status_code} {r.text}", response=r)
        return r.json()

    @staticmethod
    def get_sale_price_value(entity: dict) -> int | None:
        """
        salePrices[].value — цена в копейках.
        Берём первый уровень (MVP).
        """
        prices = entity.get("salePrices") or []
        if not prices:
            return None
        v = prices[0].get("value")
        return int(v) if v is not None else None

    # ---------------------------
    # Orders
    # ---------------------------

    def find_customer_order_by_name(self, name: str) -> dict | None:
        """
        Практически надёжно (и не ломается на спецсимволах):
        search + exact match по name.
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
