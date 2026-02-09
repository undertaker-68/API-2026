from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fbo.ozon.client import OzonClient


# Коды статусов (то, что ты уже собрал)
STATES_ALL = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

# (опционально) человекочитаемые имена — для логов/state
STATE_NAME = {
    1: "valid(no_orders)",
    2: "READY_TO_SUPPLY",
    3: "ACCEPTED_AT_SUPPLY_WAREHOUSE",
    4: "IN_TRANSIT",
    5: "ACCEPTANCE_AT_STORAGE_WAREHOUSE",
    6: "valid(no_orders)",
    7: "valid(no_orders)",
    8: "COMPLETED",
    9: "REJECTED_AT_SUPPLY_WAREHOUSE",
    10: "CANCELLED",
    11: "OVERDUE",
}


def parse_utc(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


class OzonSuppliesApi:
    def __init__(self, client: OzonClient):
        self.client = client

    def list_supplies(self, from_utc: datetime, to_utc_ex: datetime, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Рабочая схема v3 (как у тебя):
        1) list -> order_ids + last_id
        2) get  -> orders (created_date есть тут)
        Фильтр по времени делаем по orders.created_date.
        """
        last_id = None
        result: List[Dict[str, Any]] = []

        while True:
            list_payload: Dict[str, Any] = {
                "filter": {"states": STATES_ALL},
                "limit": limit,
                "sort_by": "ORDER_CREATION",
                "sort_dir": "DESC",
            }
            if last_id:
                list_payload["last_id"] = last_id

            page = self.client.post("/v3/supply-order/list", list_payload)
            order_ids = page.get("order_ids", []) or []
            if not order_ids:
                break

            min_created_page: Optional[datetime] = None

            # батчи по 50
            for i in range(0, len(order_ids), 50):
                chunk = order_ids[i : i + 50]
                details = self.client.post("/v3/supply-order/get", {"order_ids": chunk})
                orders = details.get("orders", []) or []

                for o in orders:
                    created = parse_utc(o.get("created_date"))
                    if not created:
                        continue

                    if min_created_page is None or created < min_created_page:
                        min_created_page = created

                    if from_utc <= created < to_utc_ex:
                        result.append(o)

            # ранняя остановка (DESC)
            if min_created_page and min_created_page < from_utc:
                break

            last_id = page.get("last_id")
            if not last_id:
                break

        # без дублей (на всякий)
        seen = set()
        out: List[Dict[str, Any]] = []
        for o in sorted(result, key=lambda x: (x.get("created_date", ""), x.get("order_number", ""))):
            key = (o.get("order_id"), o.get("order_number"))
            if key in seen:
                continue
            seen.add(key)
            out.append(o)
        return out

    def bundle(self, supply_order_id: int) -> List[Dict[str, Any]]:
        # как и раньше — состав поставки
        data = self.client.post("/v1/supply-order/bundle", {"supply_order_id": supply_order_id})
        result = data.get("result") or {}
        items = result.get("items") or result.get("products") or result.get("rows") or []
        return items if isinstance(items, list) else []

    @staticmethod
    def supply_id(order: Dict[str, Any]) -> Optional[int]:
        v = order.get("order_id")
        try:
            return int(v)
        except Exception:
            return None

    @staticmethod
    def supply_number(order: Dict[str, Any]) -> str:
        # номер поставки = order_number (как у тебя в примере)
        v = order.get("order_number")
        return str(v).strip() if v is not None else str(order.get("order_id"))

    @staticmethod
    def supply_status(order: Dict[str, Any]) -> str:
        st = order.get("state")
        try:
            st_i = int(st)
        except Exception:
            return "UNKNOWN"
        return STATE_NAME.get(st_i, f"STATE_{st_i}")

    @staticmethod
    def warehouse_name(order: Dict[str, Any]) -> str:
        # если в ответе есть поле склада — подхватим, иначе fallback
        for k in ("warehouse_name", "destination_warehouse_name"):
            v = order.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for k in ("warehouse", "destination_warehouse"):
            v = order.get(k)
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
