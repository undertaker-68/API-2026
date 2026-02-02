from __future__ import annotations
import requests
from datetime import datetime
from typing import List, Dict, Any, Iterable

class OzonFboClient:
    def __init__(self, client_id: str, api_key: str, timeout: int = 30):
        self.base = "https://api-seller.ozon.ru"
        self.headers = {
            "Client-Id": client_id,
            "Api-Key": api_key,
            "Content-Type": "application/json",
        }
        self.timeout = timeout

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        r = requests.post(self.base + path, headers=self.headers, json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def list_order_ids(self, since_iso: str, to_iso: str, state_enum: int, sort_by: int = 1, limit: int = 50) -> List[int]:
        body = {
            "filter": {"since": since_iso, "to": to_iso, "states": [state_enum]},
            "sort_by": sort_by,
            "limit": limit,
        }
        out = self._post("/v3/supply-order/list", body)
        return out.get("order_ids", []) or []

    def get_orders(self, order_ids: List[int]) -> List[Dict[str, Any]]:
        out = self._post("/v3/supply-order/get", {"order_ids": order_ids})
        return out.get("orders", []) or []

    def iter_bundle_items(self, bundle_id: str) -> Iterable[Dict[str, Any]]:
        last_id = ""
        while True:
            body = {"bundle_ids": [bundle_id], "limit": 100}
            if last_id != "":
                body["last_id"] = last_id
            out = self._post("/v1/supply-order/bundle", body)
            for it in out.get("items", []) or []:
                yield it
            if not out.get("has_next"):
                break
            nxt = out.get("last_id", "")
            if not nxt or nxt == last_id:
                break
            last_id = nxt
