import logging
from datetime import datetime, timedelta, timezone, date

from app.config import Config
from app.ozon_client import OzonClient
from app.ms_client import MSClient
from app.state_store import StateStore, OrderState
from app.mappers import ALLOWED_OZON_STATUSES, ms_state_id_for_ozon_status
from app.bundle_expand import expand_offer

log = logging.getLogger("sync")

OZON_MARK = "ozon"


def iso_z(d: datetime) -> str:
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compute_cutoff_window(since_date: str, days_back: int = 7, days_forward: int = 30) -> tuple[str, str]:
    since = date.fromisoformat(since_date)
    today = datetime.now(timezone.utc).date()
    start = max(since, today - timedelta(days=days_back))
    end = today + timedelta(days=days_forward)
    return (
        iso_z(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)),
        iso_z(datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)),
    )


def build_ms_positions(ms: MSClient, ozon_products: list[dict]) -> list[dict]:
    positions: list[dict] = []
    for p in ozon_products:
        offer_id = str(p.get("offer_id") or "").strip()
        qty = int(p.get("quantity") or 0)
        if not offer_id or qty <= 0:
            continue

        expanded = expand_offer(ms, offer_id, qty)
        for row in expanded:
            positions.append(row)
    return positions


def ensure_order(ms: MSClient, posting_number: str) -> tuple[str | None, str]:
    found = ms.find_customer_order_by_name(posting_number)
    if found:
        oid = found["id"]
        full = ms.get_customer_order(oid)
        desc = (full.get("description") or "")
        if f"{OZON_MARK}:{posting_number}" in desc:
            return oid, posting_number

        i = 1
        while True:
            name2 = f"{posting_number}er" if i == 1 else f"{posting_number}er{i}"
            if not ms.find_customer_order_by_name(name2):
                return None, name2
            i += 1

    return None, posting_number


def run_once(cfg: Config, store: StateStore, ozon: OzonClient, ms: MSClient, since_date: str = "2026-01-29") -> None:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    seen_now: set[str] = set()

    cutoff_from, cutoff_to = compute_cutoff_window(since_date)
    log.info("CUT window %s .. %s", cutoff_from, cutoff_to)

    # ===== АКТИВНЫЕ СТАТУСЫ =====
    for status in ("awaiting_packaging", "awaiting_deliver", "delivering"):
        try:
            resp = ozon.unfulfilled_list(cutoff_from, cutoff_to, status=status, limit=50, offset=0)
        except Exception as e:
            log.error("OZON list status=%s failed: %s", status, e)
            continue

        postings = resp.get("result", {}).get("postings") or []
        for it in postings:
            posting_number = it.get("posting_number")
            if not posting_number:
                continue

            seen_now.add(posting_number)
            s = store.get(posting_number)
            if s.forgotten:
                continue

            full = ozon.get_posting(posting_number)
            posting = full.get("result") or full
            oz_status = posting.get("status")
            cancellation = posting.get("cancellation") or {}
            initiator = cancellation.get("initiator")

            log.info("OZON posting=%s status=%s initiator=%s", posting_number, oz_status, initiator)

            ms_state_id = ms_state_id_for_ozon_status(oz_status, initiator)
            order_id = s.ms_order_id

            # --- создание заказа
            if not order_id and oz_status == "awaiting_packaging":
                existing_id, name = ensure_order(ms, posting_number)
                if existing_id:
                    order_id = existing_id
                else:
                    positions = build_ms_positions(ms, posting.get("products") or [])
                    if not cfg.dry_run:
                        created = ms.create_customer_order({
                            "name": name,
                            "organization": {"meta": {"href": f"{ms.base}/entity/organization/{cfg.org_id}", "type": "organization"}},
                            "agent": {"meta": {"href": f"{ms.base}/entity/counterparty/{cfg.agent_id}", "type": "counterparty"}},
                            "salesChannel": {"meta": {"href": f"{ms.base}/entity/saleschannel/{cfg.sales_channel_id}", "type": "saleschannel"}},
                            "store": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store"}},
                            "reserve": True,
                            "description": f"{OZON_MARK}:{posting_number}",
                            "positions": positions,
                        })
                        order_id = created["id"]
                        log.info("MS create CustomerOrder posting=%s name=%s positions=%d", posting_number, name, len(positions))

            if not order_id:
                store.upsert(OrderState(posting_number, None, oz_status, s.demand_created, s.move_created, 0, now_ts, 0))
                continue

            # --- статус МС
            if ms_state_id and not cfg.dry_run:
                ms.set_order_state(order_id, ms_state_id)

            # --- Demand
            if s.last_status == "awaiting_deliver" and oz_status == "delivering":
                if not s.demand_created:
                    if not cfg.dry_run:
                        ms.create_demand({
                            "organization": {"meta": {"href": f"{ms.base}/entity/organization/{cfg.org_id}", "type": "organization"}},
                            "agent": {"meta": {"href": f"{ms.base}/entity/counterparty/{cfg.agent_id}", "type": "counterparty"}},
                            "store": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store"}},
                            "customerOrder": {"meta": {"href": f"{ms.base}/entity/customerorder/{order_id}", "type": "customerorder"}},
                        })
                        log.info("MS create Demand posting=%s order_id=%s -> FORGET", posting_number, order_id)
                    s.demand_created = 1
                s.forgotten = 1

            store.upsert(OrderState(
                posting_number, order_id, oz_status,
                s.demand_created, s.move_created, s.forgotten,
                now_ts, 0
            ))

    # ===== FINALIZE (пропал из active) =====
    for st in store.iter_active():
        if st.posting_number in seen_now or st.forgotten:
            continue

        st.missed_cycles += 1
        if st.missed_cycles < 2:
            store.upsert(st)
            continue

        log.info("FINALIZE posting=%s was_missing cycles=%s -> get()", st.posting_number, st.missed_cycles)

        full = ozon.get_posting(st.posting_number)
        posting = full.get("result") or full
        oz_status = posting.get("status")
        initiator = (posting.get("cancellation") or {}).get("initiator")

        if oz_status == "cancelled":
            action = "reserve_off"
            if (initiator or "").upper() == "SELLER":
                action = "reserve_off+move"

            log.info(
                "CANCEL posting=%s prev=%s initiator=%s action=%s",
                st.posting_number, st.last_status, initiator, action
            )

            if st.ms_order_id and not cfg.dry_run:
                ms.set_order_reserve(st.ms_order_id, False)

                if (initiator or "").upper() == "SELLER":
                    positions = build_ms_positions(ms, posting.get("products") or [])
                    try:
                        ms.create_move({
                            "organization": {"meta": {"href": f"{ms.base}/entity/organization/{cfg.org_id}", "type": "organization"}},
                            "sourceStore": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store"}},
                            "targetStore": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_main_id}", "type": "store"}},
                            "positions": positions,
                        })
                    except Exception:
                        pass

            log.info("FORGET posting=%s reason=cancelled", st.posting_number)
            st.forgotten = 1
            st.last_status = "cancelled"
            st.missed_cycles = 0
            store.upsert(st)

        elif oz_status == "delivered":
            log.info("FORGET posting=%s reason=delivered", st.posting_number)
            st.forgotten = 1
            st.last_status = "delivered"
            st.missed_cycles = 0
            store.upsert(st)
