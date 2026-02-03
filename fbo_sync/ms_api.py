from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import requests


class MoySkladError(RuntimeError):
    def __init__(self, status: int, text: str):
        super().__init__(f"MS error {status}: {text}")
        self.status = status
        self.text = text


class MoySkladClient:
    def __init__(self, base_url: str, token: str, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

        self.s = requests.Session()
        self.s.headers.update(
            {
                "Authorization": f"Bearer {token}",
                # ВАЖНО: у MS Accept должен быть строго таким
                "Accept": "application/json;charset=utf-8",
            }
        )

        # кэши чтобы меньше ловить 429
        self._assort_cache: Dict[str, dict] = {}
        self._price_cache: Dict[str, float] = {}

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = self.base + path
        for _ in range(5):
            r = self.s.get(url, params=params, timeout=self.timeout)

            if r.status_code == 429:
                # лимит МойСклад — ждём и ретраим
                time.sleep(3)
                continue

            if r.status_code >= 400:
                raise MoySkladError(r.status_code, r.text)

            return r.json()

        # после ретраев считаем, что "нет данных"
        return {"rows": []}

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base + path
        for _ in range(5):
            r = self.s.post(url, json=body, timeout=self.timeout)

            if r.status_code == 429:
                time.sleep(3)
                continue

            if r.status_code >= 400:
                raise MoySkladError(r.status_code, r.text)

            return r.json()

        raise MoySkladError(429, "rate limit (retries exceeded)")

    # --------- helpers ---------
    @staticmethod
    def mk_ref(href: str, type_: str) -> Dict[str, Any]:
        return {"meta": {"href": href, "type": type_, "mediaType": "application/json"}}

    def find_by_name(self, entity: str, name: str) -> Optional[dict]:
        out = self._get(f"/entity/{entity}", params={"filter": f"name={name}"})
        rows = out.get("rows") or []
        return rows[0] if rows else None

    def get_assortment_by_article(self, article: str) -> Optional[dict]:
        article = str(article).strip()
        if not article:
            return None
        if article in self._assort_cache:
            return self._assort_cache[article]

        out = self._get("/entity/assortment", params={"filter": f"article={article}"})
        rows = out.get("rows") or []
        a = rows[0] if rows else None
        if a:
            self._assort_cache[article] = a
        return a

    def get_product_by_article(self, article: str) -> Optional[dict]:
        out = self._get("/entity/product", params={"filter": f"article={article}"})
        rows = out.get("rows") or []
        return rows[0] if rows else None

    def get_bundle_by_article(self, article: str) -> Optional[dict]:
        out = self._get("/entity/bundle", params={"filter": f"article={article}"})
        rows = out.get("rows") or []
        return rows[0] if rows else None

    def get_bundle_components(self, bundle_id: str) -> List[Tuple[Dict[str, Any], float]]:
        """
        Возвращает [(component_assortment_meta, qty), ...]

        ВАЖНО: /entity/bundle/{id} обычно не содержит components.rows.
        Нужно ходить в /entity/bundle/{id}/components
        """
        out = self._get(f"/entity/bundle/{bundle_id}/components", params={"limit": 1000, "offset": 0})
        rows = out.get("rows", []) or []

        res: List[Tuple[Dict[str, Any], float]] = []
        for c in rows:
            assort = c.get("assortment", {})
            meta = assort.get("meta") if isinstance(assort, dict) else None
            if not meta or not meta.get("href"):
                continue
            qty = float(c.get("quantity") or 0)
            if qty <= 0:
                continue
            res.append((meta, qty))
        return res

    def get_sale_price(self, assortment_meta_href: str) -> float:
        """
        Дефолтная цена из salePrices[0].value по meta.href сущности.
        Возвращаем в формате MS (обычно 'копейки*100').
        """
        if assortment_meta_href in self._price_cache:
            return self._price_cache[assortment_meta_href]

        path = assortment_meta_href.split("/api/remap/1.2")[-1]
        if not path.startswith("/"):
            path = "/" + path

        obj = self._get(path)
        prices = obj.get("salePrices") or []
        val = float((prices[0] or {}).get("value") or 0) if prices else 0.0

        self._price_cache[assortment_meta_href] = val
        return val

    # --------- create docs ---------
    def create_customerorder(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/customerorder", body)

    def create_customer_order(self, body: Dict[str, Any]) -> Dict[str, Any]:
        # backward compatible name
        return self.create_customerorder(body)

    def create_move(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/move", body)

    def create_demand(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/demand", body)
