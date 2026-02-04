import logging
from datetime import datetime, timedelta, timezone, date

from app.config import Config
from app.ozon_client import OzonClient
from app.ms_client import MSClient
from app.state_store import StateStore, OrderState
from app.mappers import ms_state_id_for_ozon_status
from app.bundle_expand import expand_offer

log = logging.getLogger("sync")

OZON_MARK = "ozon"  # метка в description


def iso_z(d: datetime) -> str:
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compute_cutoff_window(since_date: str, days_back: int = 7, days_forward: int = 0) -> tuple[str, str]:
    since = date.fromisoformat(since_date)
    today = datetime.now(timezone.utc).date()
    start = max(since, today - timedelta(days=days_back))
    end = today + timedelta(days=days_forward)
    return (
        iso_z(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)),
        iso_z(datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)),
    )


def build_ms_positions(ms: MSClient, ozon_products: list[dict], posting_number: str) -> list[dict]:
    """
    ВАЖНО:
      - сопоставление offer_id -> article (МС)
      - bundle разворачиваем
      - если позиция не сматчилась — пропускаем позицию, заказ НЕ дропаем целиком
    """
    positions: list[dict] = []
    for p in ozon_products:
        offer_id = str(p.get("offer_id") or "").strip()
        qty = int(p.get("quantity") or 0)
        if not offer_id or qty <= 0:
            continue

        expanded = expand_offer(ms, offer_id, qty)
        if not expanded:
            log.warning("MS product not mapped: posting=%s offer_id=%s qty=%s -> SKIP POSITION", posting_number, offer_id, qty)
            continue

        positions.extend(expanded)

    return positions


def ensure_order(ms: MSClient, posting_number: str) -> tuple[str | None, str]:
    """
    1) Если заказ с name=posting_number есть и это НАШ Ozon (по description) — возвращаем id и creation skip.
    2) Если name совпал, но это не наш Ozon — создаём с постфиксом er/er2/...
    """
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

    cutoff_from, cutoff_to = compute_cutoff_window(since_date, days_back=7, days_forward=0)
    log.info("sync CUT window %s .. %s", cutoff_from, cutoff_to)

    # ===== АКТИВНЫЕ СТАТУСЫ =====
    for status in ("awaiting_packaging", "awaiting_deliver", "delivering"):
        try:
            resp = ozon.unfulfilled_list(cutoff_from, cutoff_to, status=status, limit=50, offset=0)
        except Exception as e:
            log.error("sync OZON list status=%s failed: %s", status, e)
            continue

        postings = resp.get("result", {}).get("postings") or []
        log.info("sync OZON list status=%s postings=%d", status, len(postings))

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
                oz_status = posting.get("status") or status
                cancellation = posting.get("cancellation") or {}
                initiator = cancellation.get("initiator")

                log.info("sync OZON posting=%s status=%s initiator=%s", posting_number, oz_status, initiator)

                ms_state_id = ms_state_id_for_ozon_status(oz_status, initiator)
                order_id = s.ms_order_id

                # --- создание заказа (если его нет) — для awaiting_* и даже delivering (бывают кейсы)
                if not order_id and oz_status in ("awaiting_packaging", "awaiting_deliver", "delivering"):
                    existing_id, name = ensure_order(ms, posting_number)
                    if existing_id:
                        order_id = existing_id
                    else:
                        positions = build_ms_positions(ms, posting.get("products") or [], posting_number)

                        # если вообще ничего не сматчилось — НЕ забываем (чтобы добить после починки артикула),
                        # просто не создаём пустой заказ.
                        if not positions:
                            log.warning("MS skip create CustomerOrder posting=%s: positions=0 (all products unmapped)", posting_number)
                            store.upsert(OrderState(posting_number, None, oz_status, s.demand_created, s.move_created, 0, now_ts, 0))
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
                            ms.set_order_reserve(order_id, True)
                            log.info("MS create CustomerOrder posting=%s name=%s positions=%d", posting_number, name, len(positions))

                if not order_id:
                    store.upsert(OrderState(posting_number, None, oz_status, s.demand_created, s.move_created, 0, now_ts, 0))
                    continue

                # --- статус МС
                if ms_state_id and not cfg.dry_run:
                    ms.update_customer_order(order_id, {
                        "state": {"meta": {"href": f"{ms.base}/entity/customerorder/metadata/states/{ms_state_id}", "type": "state"}},
                        "reserve": True,
                        "store": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store"}},
                    })

                # --- Demand (защита от дублей): создаём один раз при delivering
                if oz_status == "delivering" and not s.demand_created:
                    positions = build_ms_positions(ms, posting.get("products") or [], posting_number)

                    # если не удалось собрать позиции — считаем ошибкой сопоставления, не создаём Demand и не забываем
                    if not positions:
                        log.warning("MS skip create Demand posting=%s: positions=0 (unmapped) -> will retry", posting_number)
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
                                log.info("MS create Demand posting=%s order_id=%s -> demand_created=1", posting_number, order_id)
                            except Exception as e:
                                msg = str(e)
                                log.error("MS create Demand failed posting=%s: %s", posting_number, msg)

                                # нет остатков — пропускаем и забываем
                                if "3007" in msg or "нет на складе" in msg.lower():
                                    log.warning("MS Demand blocked by stock, FORGET posting=%s", posting_number)
                                    store.upsert(OrderState(
                                        posting_number, order_id, oz_status,
                                        0, s.move_created, 1,  # forgotten = 1
                                        now_ts, 0
                                    ))
                                    continue

                                # прочие ошибки — оставляем на повтор
                                store.upsert(OrderState(posting_number, order_id, oz_status, 0, s.move_created, 0, now_ts, 0))
                                continue

                        s.demand_created = 1
                        s.forgotten = 1  # по твоему правилу: delivering->(создали demand)->забываем

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

        log.info("FINALIZE posting=%s was_missing cycles=%s -> ozon.get()", st.posting_number, st.missed_cycles)

        try:
            full = ozon.get_posting(st.posting_number)
            posting = full.get("result") or full
            oz_status = posting.get("status")
            cancellation = posting.get("cancellation") or {}
            initiator = cancellation.get("initiator")

            ms_state_id = ms_state_id_for_ozon_status(oz_status, initiator)
            order_id = st.ms_order_id

            if not order_id:
                # если у нас нет id заказа — просто забываем состояние, смысла нет
                st.forgotten = 1
                store.upsert(st)
                continue

            # обновим статус в МС (если нужно)
            if ms_state_id and not cfg.dry_run:
                ms.set_order_state(order_id, ms_state_id)

            # отмены после delivering/delivered: не удаляем demand, просто забываем
            if oz_status == "cancelled":
                # CLIENT/OZON: снять резерв и забыть
                if initiator in ("client", "ozon"):
                    if not cfg.dry_run:
                        ms.set_order_reserve(order_id, False)
                    st.forgotten = 1
                    store.upsert(st)
                    continue

                # SELLER: если отменили из awaiting_deliver — снять резерв и сделать Move (если не делали)
                if initiator == "seller":
                    if not cfg.dry_run:
                        ms.set_order_reserve(order_id, False)

                    if not st.move_created:
                        positions = build_ms_positions(ms, posting.get("products") or [], st.posting_number)
                        if positions:
                            try:
                                if not cfg.dry_run:
                                    ms.create_move({
                                        "organization": {"meta": {"href": f"{ms.base}/entity/organization/{cfg.org_id}", "type": "organization"}},
                                        "sourceStore": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store"}},
                                        "targetStore": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_main_id}", "type": "store"}},
                                        "positions": positions,
                                    })
                                st.move_created = 1
                                log.info("MS create Move posting=%s -> move_created=1", st.posting_number)
                            except Exception as e:
                                log.error("MS create Move failed posting=%s: %s (skip)", st.posting_number, e)

                    st.forgotten = 1
                    store.upsert(st)
                    continue

            # доставлен/отгружен — забываем
            if oz_status in ("delivered", "delivering"):
                st.forgotten = 1
                store.upsert(st)
                continue

            # иначе просто обновили last_seen/missed и оставили
            st.missed_cycles = 0
            st.last_seen_ts = now_ts
            store.upsert(st)

        except Exception as e:
            log.error("FINALIZE posting=%s failed: %s", st.posting_number, e, exc_info=True)
            # не забываем, попробуем в следующем цикле
            st.missed_cycles = 0
            store.upsert(st)
