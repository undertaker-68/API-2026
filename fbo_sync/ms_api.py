from __future__ import annotations

import time
import requests
from typing import Any, Dict, List, Optional, Tuple


class MoySkladError(RuntimeError):
    def __init__(self, status: int, text: str):
        super().__init__(f"MS error {status}: {text}")
        self.status = status
        self.text = text


def _is_name_conflict(payload: Any) -> bool:
    txt = str(payload).lower()
    return ("name" in txt) or ("номер" in txt)


class MoySkladClient:
    """
    ВАЖНО:
    - Accept строго application/json;charset=utf-8
    - GET без Content-Type (иначе у некоторых прокси/ngx бывает 415)
    """

    def __init__(self, base_url: str, token: str, timeout: int = 30, retries: int = 8):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.s = requests.Session()
        self.s.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json;charset=utf-8",
            }
        )
        self._price_cache: Dict[str, int] = {}

    def _sleep_on_429(self, r: requests.Response, attempt: int) -> None:
        ra = r.headers.get("x-lognex-retry-after")
        ti = r.headers.get("x-lognex-retry-timeinterval")
        wait_ms: Optional[int] = None
        if ra and ra.isdigit():
            wait_ms = int(ra)
        elif ti and ti.isdigit():
            wait_ms = int(ti)
        if wait_ms is None:
            wait_ms = min(3000 * (attempt + 1), 15000)
        time.sleep(wait_ms / 1000.0)

    def _get(self, path: str, params: dict | None = None) -> Dict[str, Any]:
        last_err = None
        for attempt in range(self.retries):
            r = self.s.get(self.base + path, params=params, timeout=self.timeout)
            if r.status_code == 429:
                last_err = r.text
                self._sleep_on_429(r, attempt)
                continue
            if r.status_code >= 400:
                raise MoySkladError(r.status_code, r.text)
            return r.json()
        raise MoySkladError(429, last_err or "Rate limit (retries exceeded)")

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        last_err = None
        for attempt in range(self.retries):
            r = self.s.post(
                self.base + path,
                json=body,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
            if r.status_code == 429:
                last_err = r.text
                self._sleep_on_429(r, attempt)
                continue
            if r.status_code >= 400:
                raise MoySkladError(r.status_code, r.text)
            return r.json()
        raise MoySkladError(429, last_err or "Rate limit (retries exceeded)")

    # ---------------- refs ----------------

    def mk_ref(self, entity: str, id_: str) -> Dict[str, Any]:
        return {
            "meta": {
                "href": f"{self.base}/entity/{entity}/{id_}",
                "type": entity,
                "mediaType": "application/json",
            }
        }

    def mk_doc_state_ref(self, doc_entity: str, state_id: str) -> Dict[str, Any]:
        """
        doc_entity: customerorder / demand / move
        state href у МС лежит в metadata/states
        """
        return {
            "meta": {
                "href": f"{self.base}/entity/{doc_entity}/metadata/states/{state_id}",
                "type": "state",
                "mediaType": "application/json",
            }
        }

    # ---------------- find / assortment ----------------

    def find_by_name(self, entity: str, name: str) -> Optional[dict]:
        out = self._get(f"/entity/{entity}", params={"filter": f"name={name}"})
        rows = out.get("rows") or []
        return rows[0] if rows else None

    def get_assortment_by_article(self, article: str) -> Optional[dict]:
        out = self._get("/entity/assortment", params={"filter": f"article={article}"})
        rows = out.get("rows") or []
        return rows[0] if rows else None

    def get_bundle_components(self, bundle_id: str) -> List[Tuple[Dict[str, Any], float]]:
        """
        Возвращает [(assortment_meta, qty), ...]
        """
        out = self._get(f"/entity/bundle/{bundle_id}/components", params={"limit": 1000})
        rows = out.get("rows") or []
        res: List[Tuple[Dict[str, Any], float]] = []
        for r in rows:
            res.append((r["assortment"]["meta"], float(r.get("quantity") or 0)))
        return res

    def get_sale_price_by_href(self, href: str) -> int:
        """
        Берём "цену продажи" из salePrices[0].value.
        value у МС в копейках.
        """
        if href in self._price_cache:
            return self._price_cache[href]

        # href -> path
        marker = "/api/remap/1.2"
        if marker in href:
            path = href.split(marker, 1)[1]
        else:
            # на всякий
            path = "/" + "/".join(href.split("/entity/", 1)[1].split("/"))
        if not path.startswith("/"):
            path = "/" + path

        obj = self._get(path)
        sale_prices = obj.get("salePrices") or []
        price = 0
        if sale_prices:
            price = int(sale_prices[0].get("value") or 0)

        self._price_cache[href] = price
        return price

    # ---------------- create docs ----------------

    def create_customer_order(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/customerorder", body)

    def create_move(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/move", body)

    def create_demand(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/demand", body)

    def try_create_move_with_fallback(self, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Если конфликт по name — пропускаем (считаем что уже есть/не надо).
        Иначе пробуем applicable true/false.
        """
        b1 = dict(body)
        b1["applicable"] = True
        try:
            return self.create_move(b1)
        except MoySkladError as e:
            if _is_name_conflict(e.text):
                return None
            b2 = dict(body)
            b2["applicable"] = False
            try:
                return self.create_move(b2)
            except MoySkladError as e2:
                if _is_name_conflict(e2.text):
                    return None
                raise


# ---- backward compatible aliases (чтоб REPL и старые импорты не ломались) ----
MS = MoySkladClient
MoySklad = MoySkladClient
