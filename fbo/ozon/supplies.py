from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from fbo.ozon.client import OzonClient


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
        if isinstance(st, str) and st and not st.isdigit():
            return st.strip()
        try:
            st_i = int(st)
        except Exception:
            return "UNKNOWN"
        return STATE_NAME.get(st_i, f"STATE_{st_i}")

    # ====== ВАЖНО: совместимость с runner.py из архива ======

    @staticmethod
    def destination_warehouse_name(order: Dict[str, Any]) -> str:
        """
        Склад назначения (куда едет на хранение): supplies[0].storage_warehouse.name
        """
        supplies = order.get("supplies")
        if isinstance(supplies, list) and supplies:
            s0 = supplies[0]
            if isinstance(s0, dict):
                sw = s0.get("storage_warehouse")
                if isinstance(sw, dict):
                    name = sw.get("name")
                    if isinstance(name, str) and name.strip():
                        return name.strip()
        return "Ozon"

    @staticmethod
    def planned_timeslot_to(order: Dict[str, Any]) -> Optional[str]:
        """
        timeslot.timeslot.to (ISO Z). Если to нет — берём from.
        """
        ts = order.get("timeslot")
        if isinstance(ts, dict):
            t2 = ts.get("timeslot")
            if isinstance(t2, dict):
                to = t2.get("to")
                if isinstance(to, str) and to.strip():
                    return to.strip()
                fr = t2.get("from")
                if isinstance(fr, str) and fr.strip():
                    return fr.strip()
        return None

    @staticmethod
    def arrival_date(order: Dict[str, Any]) -> Optional[str]:
        """
        supplies[0].storage_warehouse.arrival_date (если нужно как fallback).
        """
        supplies = order.get("supplies")
        if isinstance(supplies, list) and supplies:
            sw = supplies[0].get("storage_warehouse")
            if isinstance(sw, dict):
                v = sw.get("arrival_date")
                if isinstance(v, str) and v.strip():
                    return v.strip()
        return None

    @staticmethod
    def warehouse_name(order: Dict[str, Any]) -> str:
        """
        runner.py ожидает warehouse_name() -> используем destination_warehouse_name()
        """
        return OzonSuppliesApi.destination_warehouse_name(order)

    @staticmethod
    def planned_moment(order: Dict[str, Any]) -> Optional[str]:
        """
        runner.py ожидает planned_moment().
        По бизнесу: берём timeslot.to (дата/время отгрузки).
        Если timeslot нет — fallback на arrival_date.
        """
        return OzonSuppliesApi.planned_timeslot_to(order) or OzonSuppliesApi.arrival_date(order)

    # ====== offer_id -> article (ВАЖНО) ======

    @staticmethod
    def _find_offer_id(x: Any) -> Optional[str]:
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "offer_id" and isinstance(v, str) and v.strip():
                    return v.strip()
            for v in x.values():
                r = OzonSuppliesApi._find_offer_id(v)
                if r:
                    return r
        elif isinstance(x, list):
            for i in x:
                r = OzonSuppliesApi._find_offer_id(i)
                if r:
                    return r
        return None

    @staticmethod
    def extract_items_from_bundle_items(bundle_items: List[Dict[str, Any]]) -> List[Tuple[str, float]]:
        """
        Берём ТОЛЬКО offer_id (это == article в МС).
        """
        out: List[Tuple[str, float]] = []
        for it in bundle_items:
            if not isinstance(it, dict):
                continue
            offer_id = OzonSuppliesApi._find_offer_id(it)
            qty = it.get("quantity") or it.get("qty") or it.get("count")
            if not offer_id or qty is None:
                continue
            try:
                q = float(qty)
            except Exception:
                continue
            if q <= 0:
                continue
            out.append((offer_id, q))
        return out
