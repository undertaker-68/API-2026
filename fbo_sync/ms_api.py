from __future__ import annotations

import time
from typing import Dict, Any, List, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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

        # ВАЖНО: без Content-Type на GET (иначе у вас 415 от nginx)
        self.s.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json;charset=utf-8",
            }
        )

        # (connect, read) — чтобы не висеть бесконечно на ответе
        # timeout аргумент оставляем для совместимости, но используем tuple
        self.timeout = (3, min(int(timeout), 30))

        # Нормальные ретраи на сетевые ошибки и временные статусы
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST", "PUT", "DELETE"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        self.s.mount("https://", adapter)
        self.s.mount("http://", adapter)

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            r = self.s.get(self.base + path, params=params, timeout=self.timeout)
        except Exception:
            # сеть/таймаут/обрыв — не стопорим цикл, считаем что данных нет
            return {"rows": []}

        if r.status_code == 429:
            # лимит МойСклад — просто считаем, что данных нет
            return {"rows": []}

        if r.status_code >= 400:
            raise MoySkladError(r.status_code, r.text)

        return r.json()

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            r = self.s.post(self.base + path, json=body, timeout=self.timeout)
        except Exception as e:
            raise MoySkladError(0, f"network/post failed: {e}")

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
        # /entity/bundle/{id}/components
        out = self._get(f"/entity/bundle/{bundle_id}/components", params={"limit": 1000})
        rows = out.get("rows", []) or []
        res: List[Tuple[Dict[str, Any], float]] = []
        for c in rows:
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
