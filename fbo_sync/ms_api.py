from __future__ import annotations
import time
import requests
from typing import Dict, Any, List, Tuple


class MoySkladError(Exception):
    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        super().__init__(f"MS error {status}: {payload}")


def _is_name_conflict(payload: Any) -> bool:
    txt = str(payload).lower()
    return ("name" in txt) or ("номер" in txt)


class MoySkladClient:
    def __init__(self, base_url: str, token: str, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        # ВАЖНО: без Content-Type на GET (у вас иначе 415 от nginx)
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json;charset=utf-8",
        })
        self.timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> dict:
        # retry на 429
        delay = 1.0
        for _ in range(5):
            r = self.s.get(self.base + path, params=params, timeout=self.timeout)
            if r.status_code != 429:
                break
            time.sleep(delay)
            delay = min(delay * 2.0, 8.0)

        if r.status_code == 429:
            return {"rows": []}

        if r.status_code >= 400:
            raise MoySkladError(r.status_code, r.text)

        return r.json()

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        delay = 1.0
        for _ in range(5):
            r = self.s.post(self.base + path, json=body, timeout=self.timeout)
            if r.status_code != 429:
                break
            time.sleep(delay)
            delay = min(delay * 2.0, 8.0)

        if r.status_code == 429:
            raise MoySkladError(429, r.text)

        if r.status_code >= 400:
            raise MoySkladError(r.status_code, r.text)

        return r.json()

    def find_by_name(self, entity: str, name: str) -> Dict[str, Any] | None:
        out = self._get(f"/entity/{entity}", params={"filter": f"name={name}"})
        rows = out.get("rows", []) or []
        return rows[0] if rows else None

    def get_assortment_by_article(self, article: str) -> Dict[str, Any] | None:
        out = self._get("/entity/assortment", params={"filter": f"article={article}"})
        rows = out.get("rows", []) or []
        return rows[0] if rows else None

    def get_bundle_components(self, bundle_id: str) -> List[Tuple[Dict[str, Any], float]]:
        # returns [(component_assortment_meta, qty), ...]
        bundle = self._get(f"/entity/bundle/{bundle_id}")
        comps = bundle.get("components", {}).get("rows", []) or []
        res: List[Tuple[Dict[str, Any], float]] = []
        for c in comps:
            res.append((c["assortment"]["meta"], float(c["quantity"])))
        return res

    def mk_ref(self, entity: str, id_: str) -> Dict[str, Any]:
        return {
            "meta": {
                "href": f"{self.base}/entity/{entity}/{id_}",
                "type": entity,
                "mediaType": "application/json",
            }
        }

    def create_customer_order(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/customerorder", body)

    def create_move(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/move", body)

    def create_demand(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/demand", body)

    def try_create_move_with_fallback(self, body: Dict[str, Any]) -> Dict[str, Any] | None:
        b1 = dict(body)
        b1["applicable"] = True
        try:
            return self.create_move(b1)
        except MoySkladError as e:
            if _is_name_conflict(e.payload):
                return None
            b2 = dict(body)
            b2["applicable"] = False
            try:
                return self.create_move(b2)
            except MoySkladError as e2:
                if _is_name_conflict(e2.payload):
                    return None
                raise
