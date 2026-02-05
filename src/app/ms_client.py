import logging
from typing import Optional

import requests
from app.config import Config

log = logging.getLogger("ms")


class MSClient:
    """
    Минимальный клиент МойСклад REMAP 1.2
    """

    def __init__(self, cfg_or_token: Config | str, base: str | None = None):
        if hasattr(cfg_or_token, "ms_token"):
            cfg: Config = cfg_or_token
            token = cfg.ms_token
            base_url = cfg.ms_base_url
        else:
            token = str(cfg_or_token)
            base_url = base or "https://api.moysklad.ru/api/remap/1.2"

        self.base = base_url.rstrip("/")
        self.token = token.strip()

        if not self.token:
            raise ValueError("MS_TOKEN is empty")

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json;charset=utf-8",
            "Content-Type": "application/json",
        }

    # -----------------------------
    # Low-level HTTP
    # -----------------------------
    def _request(self, method: str, path: str, params=None, body=None) -> dict:
        url = f"{self.base}{path}"
        r = requests.request(
            method=method,
            url=url,
            headers=self.headers,
            params=params,
            json=body,
            timeout=30,
        )
        if r.status_code >= 400:
            log.error("MS %s %s failed: %s %s", method, path, r.status_code, r.text)
            raise requests.HTTPError(r.text)
        return r.json() if r.text else {}

    def _get(self, path: str, params=None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, body=body)

    def _put(self, path: str, body: dict) -> dict:
        return self._request("PUT", path, body=body)

    def _patch(self, path: str, body: dict) -> dict:
        return self._request("PATCH", path, body=body)

    # -----------------------------
    # CustomerOrder
    # -----------------------------
    def find_customer_order_by_name(self, name: str) -> Optional[dict]:
        res = self._get("/entity/customerorder", params={"search": name})
        for r in res.get("rows") or []:
            if r.get("name") == name:
                return r
        return None

    def get_customer_order(self, order_id: str) -> dict:
        return self._get(f"/entity/customerorder/{order_id}")

    def create_customer_order(self, body: dict) -> dict:
        return self._post("/entity/customerorder", body)

    def set_order_state(self, order_id: str, state_id: str) -> dict:
        return self._patch(f"/entity/customerorder/{order_id}", {
            "state": {
                "meta": {
                    "href": f"{self.base}/entity/customerorder/metadata/states/{state_id}",
                    "type": "state",
                }
            }
        })

    # -----------------------------
    # REAL reserve (positions[].reserve)
    # -----------------------------
    def get_customer_order_positions(self, order_id: str) -> list[dict]:
        o = self._get(f"/entity/customerorder/{order_id}", params={"expand": "positions"})
        return (o.get("positions") or {}).get("rows") or []

    def set_positions_reserve_all(self, order_id: str, reserve_on: bool) -> dict:
        rows = self.get_customer_order_positions(order_id)
        if not rows:
            return {}

        payload = {
            "positions": [
                {
                    "id": p["id"],
                    "reserve": (p.get("quantity", 0) if reserve_on else 0),
                }
                for p in rows
                if p.get("id")
            ]
        }
        return self._put(f"/entity/customerorder/{order_id}", payload)

    # -----------------------------
    # Demand / Move
    # -----------------------------
    def create_demand(self, body: dict) -> dict:
        return self._post("/entity/demand", body)

    def create_move(self, body: dict) -> dict:
        return self._post("/entity/move", body)
