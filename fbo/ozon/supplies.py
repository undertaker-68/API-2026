from __future__ import annotations

from typing import Any, Dict, List

import requests
from fbo.ozon.client import OzonClient


class OzonSuppliesApi:
    def __init__(self, client: OzonClient):
        self.client = client

    def _post_try(self, paths: List[str], payload: Dict[str, Any]) -> Dict[str, Any]:
        last_err: Exception | None = None
        for p in paths:
            try:
                return self.client.post(p, payload)
            except requests.HTTPError as e:
                last_err = e
        assert last_err is not None
        raise last_err

    def list_supplies(self, created_from_iso: str, created_to_iso: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Пробуем v3 -> v2 -> v1.
        (в новостях/уведомлениях встречается v3 для list, а v2 официально используется/использовался ранее)
        """
        out: List[Dict[str, Any]] = []
        offset = 0
        while True:
            payload = {
                "filter": {
                    "created_at_from": created_from_iso,
                    "created_at_to": created_to_iso,
                },
                "limit": limit,
                "offset": offset,
            }

            data = self._post_try(
                ["/v3/supply-order/list", "/v2/supply-order/list", "/v1/supply-order/list"],
                payload,
            )

            result = data.get("result") or {}
            items = result.get("supply_orders") or result.get("items") or result.get("rows") or []
            if not isinstance(items, list):
                items = []

            out.extend(items)
            if len(items) < limit:
                break
            offset += limit

        return out

    def get_supply(self, supply_order_id: int) -> Dict[str, Any]:
        payload = {"supply_order_id": supply_order_id}
        data = self._post_try(
            ["/v3/supply-order/get", "/v2/supply-order/get", "/v1/supply-order/get"],
            payload,
        )
        return data.get("result") or {}

    def bundle(self, supply_order_id: int) -> List[Dict[str, Any]]:
        # bundle чаще живёт в v1 (и его рекомендуют вместо items)
        data = self._post_try(
            ["/v1/supply-order/bundle"],
            {"supply_order_id": supply_order_id},
        )
        result = data.get("result") or {}
        items = result.get("items") or result.get("products") or result.get("rows") or []
        return items if isinstance(items, list) else []

    @staticmethod
    def supply_id(s: Dict[str, Any]) -> int | None:
        v = s.get("supply_order_id") or s.get("id")
        try:
            return int(v)
        except Exception:
            return None

    @staticmethod
    def supply_number(s: Dict[str, Any], info: Dict[str, Any]) -> str:
        for k in ("supply_order_number", "number", "posting_number", "name"):
            v = s.get(k) or info.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        sid = s.get("supply_order_id") or info.get("supply_order_id") or s.get("id") or info.get("id")
        return str(sid)

    @staticmethod
    def supply_status(s: Dict[str, Any], info: Dict[str, Any]) -> str:
        for k in ("status", "state", "supply_order_status"):
            v = s.get(k) or info.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return "UNKNOWN"

    @staticmethod
    def warehouse_name(info: Dict[str, Any]) -> str:
        for k in ("warehouse_name", "destination_warehouse_name"):
            v = info.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for k in ("warehouse", "destination_warehouse"):
            v = info.get(k)
            if isinstance(v, dict):
                name = v.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
        return "Ozon"

    @staticmethod
    def extract_items(bundle_items: List[Dict[str, Any]]) -> List[tuple[str, float]]:
        out: List[tuple[str, float]] = []
        for it in bundle_items:
            offer_id = it.get("offer_id") or it.get("sku") or it.get("article") or it.get("merchant_sku")
            qty = it.get("quantity") or it.get("qty") or it.get("count")
            if offer_id is None or qty is None:
                continue
            try:
                q = float(qty)
            except Exception:
                continue
            if q <= 0:
                continue
            out.append((str(offer_id).strip(), q))
        return out
