from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fbo.ozon.client import OzonClient


# Коды статусов (то, что ты уже собрал)
STATES_ALL = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

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

    def list_supply_orders(self, from_utc: datetime, to_utc_ex: datetime, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Возвращает orders (деталка) в окне дат:
        list -> order_ids + last_id
        get  -> orders (created_date)
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

        # дедуп
        seen = set()
        out: List[Dict[str, Any]] = []
        for o in sorted(result, key=lambda x: (x.get("created_date", ""), x.get("order_number", ""))):
            key = (o.get("order_id"), o.get("order_number"))
            if key in seen:
                continue
            seen.add(key)
            out.append(o)
        return out

    # -------- bundle ids extraction / bundle items --------

    @staticmethod
    def extract_bundle_ids(obj: Any) -> List[str]:
        bundle_ids: set[str] = set()

        def walk(x: Any) -> None:
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in ("bundle_id", "restricted_bundle_id") and isinstance(v, str) and v:
                        bundle_ids.add(v)
                    walk(v)
            elif isinstance(x, list):
                for i in x:
                    walk(i)

        walk(obj)
        return list(bundle_ids)

    def get_supply_items(self, order_id: int) -> List[Dict[str, Any]]:
        """
        ТВОЯ рабочая схема:
        - get -> находим bundle_ids
        - bundle -> тянем items постранично по last_id
        """
        info = self.client.post("/v3/supply-order/get", {"order_ids": [order_id]})
        bundle_ids = self.extract_bundle_ids(info)
        if not bundle_ids:
            raise RuntimeError(f"bundle_ids не найдены для order_id={order_id}")

        items: List[Dict[str, Any]] = []
        last_id = ""

        while True:
            payload: Dict[str, Any] = {"bundle_ids": bundle_ids, "limit": 100, "is_asc": True}
            if last_id:
                payload["last_id"] = last_id

            data = self.client.post("/v1/supply-order/bundle", payload)

            batch = data.get("items") or []
            if isinstance(batch, list):
                items.extend(batch)

            next_last_id = data.get("last_id") or ""
            has_next = data.get("has_next")

            if not next_last_id or has_next is False or next_last_id == last_id:
                break
            last_id = next_last_id

        return items

    # -------- helpers for mapping --------

    @staticmethod
    def supply_id(order: Dict[str, Any]) -> Optional[int]:
        v = order.get("order_id")
        try:
            return int(v)
        except Exception:
            return None

    @staticmethod
    def supply_number(order: Dict[str, Any]) -> str:
        v = order.get("order_number")
        return str(v).strip() if v is not None else str(order.get("order_id"))

    @staticmethod
    def supply_status(order: Dict[str, Any]) -> str:
        st = order.get("state")

        # если уже строка статуса (READY_TO_SUPPLY, IN_TRANSIT...)
        if isinstance(st, str) and st and not st.isdigit():
            return st.strip()

        # если число или строка-число
        try:
            st_i = int(st)
        except Exception:
            return "UNKNOWN"

        return STATE_NAME.get(st_i, f"STATE_{st_i}")

    @staticmethod
    def warehouse_name(order: dict) -> str:
        # Нужен конечный склад поставки: supplies[0].storage_warehouse.name
        supplies = order.get("supplies")
        if isinstance(supplies, list) and supplies:
            s0 = supplies[0]
            if isinstance(s0, dict):
                sw = s0.get("storage_warehouse")
                if isinstance(sw, dict):
                    v = sw.get("name")
                    if isinstance(v, str) and v.strip():
                        return v.strip()

        # fallback: drop_off_warehouse (пункт сдачи)
        dow = order.get("drop_off_warehouse")
        if isinstance(dow, dict):
            for k in ("name", "title"):
                v = dow.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()

        return "Склад"
    
    @staticmethod
    def planned_moment(order: Dict[str, Any]) -> Optional[str]:
        """
        Для МС customerorder.deliveryPlannedMoment:
        берём timeslot.timeslot.from (fallback to) и отдаём в формате МС: YYYY-MM-DD HH:mm:ss.000
        """
        ts = order.get("timeslot")
        if isinstance(ts, dict):
            ts2 = ts.get("timeslot")
        else:
            ts2 = None

        src = None
        if isinstance(ts2, dict):
            src = ts2.get("from") or ts2.get("to")

        dt = parse_utc(src if isinstance(src, str) else None)
        if not dt:
            return None

        # МС в вашем проекте шлёт момент как "YYYY-MM-DD HH:mm:ss.000"
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000")

    @staticmethod
    def extract_items_from_bundle_items(bundle_items: list[dict]) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []

        def pick_offer_id(it: dict) -> str | None:
            # реальные варианты ключей
            for k in ("offer_id", "offerId", "offerID", "merchant_sku", "article"):
                v = it.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return None

        def pick_qty(it: dict) -> float | None:
            for k in ("quantity", "qty", "count"):
                v = it.get(k)
                if v is None:
                    continue
                try:
                    q = float(v)
                    return q if q > 0 else None
                except Exception:
                    continue
            return None

        for it in bundle_items:
            if not isinstance(it, dict):
                continue

            offer = pick_offer_id(it)
            qty = pick_qty(it)

            if not offer or qty is None:
                continue

            out.append((offer, qty))

        return out