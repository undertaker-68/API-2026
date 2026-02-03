from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Optional

import requests


class OzonFBO:
    def __init__(self, base_url: str, client_id: str, api_key: str, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Client-Id": str(client_id),
            "Api-Key": api_key,
            "Content-Type": "application/json",
        }

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        for _ in range(6):
            r = requests.post(self.base + path, headers=self.headers, json=body, timeout=self.timeout)
            if r.status_code == 429:
                time.sleep(2)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    def list_orders(self, since: str, to: str, states: List[int], limit: int = 50) -> List[int]:
        out = self._post(
            "/v3/supply-order/list",
            {"filter": {"since": since, "to": to, "states": states}, "sort_by": 1, "limit": limit},
        )
        return list(out.get("order_ids") or [])

    def get_orders(self, order_ids: List[int]) -> List[dict]:
        out = self._post("/v3/supply-order/get", {"order_ids": order_ids})
        return list(out.get("orders") or [])

    def iter_bundle_items(self, bundle_id: str) -> Iterator[dict]:
        last_id: Optional[str] = None
        while True:
            body = {"bundle_ids": [bundle_id], "limit": 100}
            if last_id is not None:
                body["last_id"] = str(last_id)
            out = self._post("/v1/supply-order/bundle", body)

            for it in out.get("items") or []:
                yield it

            if not out.get("has_next"):
                break
            last_id = out.get("last_id")
            if not last_id:
                break
