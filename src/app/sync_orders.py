import logging
from datetime import datetime, timedelta, timezone, date

from app.ms_client import MSClient
from app.ozon_client import OzonClient
from app.state_store import StateStore, OrderState
from app.mappers import ms_state_id_for_ozon_status
from app.bundle_expand import expand_offer
from app.config import Config

log = logging.getLogger("sync")
OZON_MARK = "ozon"


def build_ms_positions(ms: MSClient, ozon_products: list[dict], posting_number: str) -> list[dict]:
    positions = []
    for p in ozon_products:
        offer_id = str(p.get("offer_id") or "").strip()
        qty = int(p.get("quantity") or 0)
        if not offer_id or qty <= 0:
            continue

        expanded = expand_offer(ms, offer_id, qty)
        if expanded:
            positions.extend(expanded)
        else:
            log.warning("MS product not mapped posting=%s offer_id=%s", posting_number, offer_id)
    return positions


def run_once(cfg: Config, store: StateStore, ozon: OzonClient, ms: MSClient, since_date: str):
    now_ts = int(datetime.now(timezone.utc).timestamp())

    for status in ("awaiting_packaging", "awaiting_deliver", "delivering"):
        resp = ozon.unfulfilled_list("", "", status=status)
        postings = resp.get("result", {}).get("postings") or []

        for it in postings:
            posting_number = it.get("posting_number")
            s = store.get(posting_number)

            posting = ozon.get_posting(posting_number).get("result")
            oz_status = posting.get("status")
            ms_state_id = ms_state_id_for_ozon_status(oz_status, None)

            order_id = s.ms_order_id

            if not order_id:
                positions = build_ms_positions(ms, posting.get("products") or [], posting_number)
                if not positions:
                    continue

                created = ms.create_customer_order({
                    "name": posting_number,
                    "organization": {"meta": {"href": f"{ms.base}/entity/organization/{cfg.org_id}", "type": "organization"}},
                    "agent": {"meta": {"href": f"{ms.base}/entity/counterparty/{cfg.agent_id}", "type": "counterparty"}},
                    "salesChannel": {"meta": {"href": f"{ms.base}/entity/saleschannel/{cfg.sales_channel_id}", "type": "saleschannel"}},
                    "store": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store"}},
                    "description": f"{OZON_MARK}:{posting_number}",
                    "positions": positions,
                })
                order_id = created["id"]

                # 🔥 РЕАЛЬНЫЙ РЕЗЕРВ
                ms.set_positions_reserve_all(order_id, True)

            if ms_state_id:
                ms.set_order_state(order_id, ms_state_id)
                ms.set_positions_reserve_all(order_id, True)

            if oz_status == "delivering" and not s.demand_created:
                ms.create_demand({
                    "organization": {"meta": {"href": f"{ms.base}/entity/organization/{cfg.org_id}", "type": "organization"}},
                    "agent": {"meta": {"href": f"{ms.base}/entity/counterparty/{cfg.agent_id}", "type": "counterparty"}},
                    "store": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store"}},
                    "customerOrder": {"meta": {"href": f"{ms.base}/entity/customerorder/{order_id}", "type": "customerorder"}},
                    "positions": build_ms_positions(ms, posting.get("products") or [], posting_number),
                })
                s.demand_created = 1
                s.forgotten = 1

            store.upsert(OrderState(
                posting_number, order_id, oz_status,
                s.demand_created, s.move_created, s.forgotten,
                now_ts, 0
            ))
