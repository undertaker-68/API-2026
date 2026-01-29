import logging
from datetime import datetime, timedelta, timezone, date

from app.config import Config
from app.ozon_client import OzonClient
from app.ms_client import MSClient
from app.state_store import StateStore, OrderState
from app.mappers import ms_state_id_for_ozon_status
from app.bundle_expand import expand_offer

log = logging.getLogger("sync")

OZON_MARK = "ozon"


def iso_z(d: datetime) -> str:
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compute_cutoff_window(since_date: str, days_back: int = 7, days_forward: int = 0) -> tuple[str, str]:
    # окно: назад 7 дней, но не раньше since_date; вперед НЕ лезем
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
        positions.extend(expand_offer(ms, offer_id, qty))
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

            try:
                full = ozon.get_posting(posting_number)
                posting = full.get("result") or full
                oz_status = posting.get("status")
                cancellation = posting.get("cancellation") or {}
                initiator = cancellation.get("initiator")

                log.info("OZON posting=%s status=%s initiator=%s", posting_number, oz_status, initiator)

                ms_state_id = ms_state_id_for_ozon_status(oz_status, initiator)
                order_id = s.ms_order_id

                # --- СОЗДАНИЕ ЗАКАЗА: теперь и на awaiting_deliver и на delivering (чтобы свежие не терялись)
                if not order_id and oz_status in ("awaiting_packaging", "awaiting_deliver", "delivering"):
                    existing_id, name = ensure_order(ms, posting_number)
                    if existing_id:
                        order_id = existing_id
                    else:
                        positions = build_ms_positions(ms, posting.get("products") or [])
                        if not positions:
                            log.warning(
                                "MS skip create CustomerOrder posting=%s: no positions (products not mapped)",
                                posting_number,
                            )
                            store.upsert(OrderState(posting_number, None, oz_status, s.demand_created, s.move_created, 1, now_ts, 0))
                            continue

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

                # если заказа в МС нет — просто обновляем стейт и идем дальше
                if not order_id:
                    store.upsert(OrderState(posting_number, None, oz_status, s.demand_created, s.move_created, 0, now_ts, 0))
                    continue

                # --- статус МС
                if ms_state_id and not cfg.dry_run:
                    ms.set_order_state(order_id, ms_state_id)

                # --- Demand (защита от дублей + обработка, если впервые увидели сразу delivering)
                if oz_status == "delivering":
                    if s.demand_created:
                        # demand уже создавали — забываем
                        s.forgotten = 1
                    else:
                        positions = build_ms_positions(ms, posting.get("products") or [])
                        if not positions:
                            log.warning("MS skip create Demand posting=%s: no positions", posting_number)
                            s.demand_created = 1
                            s.forgotten = 1
                        else:
                            if not cfg.dry_run:
                                try:
                                    ms.create_demand({
                                        "organization": {"meta": {"href": f"{ms.base}/entity/organization/{cfg.org_id}", "type": "organization"}},
                                        "agent": {"meta": {"href": f"{ms.base}/entity/counterparty/{cfg.agent_id}", "type": "counterparty"}},
                                        "store": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store"}},
                                        "customerOrder": {"meta": {"href": f"{ms.base}/entity/customerorder/{order_id}", "type": "customerorder"}},
                                        "positions": positions,
                                    })
                                    log.info("MS create Demand posting=%s order_id=%s -> FORGET", posting_number, order_id)
                                except Exception as e:
                                    # по ТЗ: если не удалось (недостаток/ошибка) — забываем, demand не удаляем
                                    log.error("MS create Demand failed posting=%s: %s -> FORGET", posting_number, e)
                            s.demand_created = 1
                            s.forgotten = 1

                store.upsert(OrderState(
                    posting_number, order_id, oz_status,
                    s.demand_created, s.move_created, s.forgotten,
                    now_ts, 0
                ))

            except Exception as e:
                log.error("posting=%s failed: %s", posting_number, e, exc_info=True)
                continue

    # ===== FINALIZE (пропал из active) =====
    for st in store.iter_active():
        if st.posting_number in seen_now or st.forgotten:
            continue

        st.missed_cycles += 1
        if st.missed_cycles < 2:
            store.upsert(st)
            continue

        log.info("FINALIZE posting=%s was_missing cycles=%s -> get()", st.posting_number, st.missed_cycles)

        try:
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
                    # статус в МС
                    ms_state_id = ms_state_id_for_ozon_status("cancelled", initiator)
                    if ms_state_id:
                        ms.set_order_state(st.ms_order_id, ms_state_id)
                    # снять резерв
                    ms.set_order_reserve(st.ms_order_id, False)

                    # move только если SELLER и еще не делали
                    if (initiator or "").upper() == "SELLER" and not st.move_created:
                        positions = build_ms_positions(ms, posting.get("products") or [])
                        try:
                            if positions:
                                ms.create_move({
                                    "organization": {"meta": {"href": f"{ms.base}/entity/organization/{cfg.org_id}", "type": "organization"}},
                                    "sourceStore": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store"}},
                                    "targetStore": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_main_id}", "type": "store"}},
                                    "positions": positions,
                                })
                                st.move_created = 1
                        except Exception as e:
                            log.error("MS create Move failed posting=%s: %s (skip)", st.posting_number, e)

                log.info("FORGET posting=%s reason=cancelled", st.posting_number)
                st.forgotten = 1
                st.last_status = "cancelled"
                st.missed_cycles = 0
                store.upsert(st)

            elif oz_status == "delivered":
                if st.ms_order_id and not cfg.dry_run:
                    ms_state_id = ms_state_id_for_ozon_status("delivered", None)
                    if ms_state_id:
                        ms.set_order_state(st.ms_order_id, ms_state_id)

                log.info("FORGET posting=%s reason=delivered", st.posting_number)
                st.forgotten = 1
                st.last_status = "delivered"
                st.missed_cycles = 0
                store.upsert(st)

            else:
                # если пропал из active, но статус не финальный — просто сбрасываем missed_cycles
                st.missed_cycles = 0
                store.upsert(st)

        except Exception as e:
            log.error("FINALIZE posting=%s failed: %s", st.posting_number, e, exc_info=True)
            # не забываем, чтобы попробовать снова
            store.upsert(st)
