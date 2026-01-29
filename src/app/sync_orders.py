import logging
from datetime import datetime, timedelta, timezone, date

from app.config import Config
from app.ozon_client import OzonClient
from app.ms_client import MSClient
from app.state_store import StateStore, OrderState
from app.mappers import ALLOWED_OZON_STATUSES, ms_state_id_for_ozon_status
from app.bundle_expand import expand_offer

log = logging.getLogger("sync")

OZON_MARK = "ozon"  # метка в description


def iso_z(d: datetime) -> str:
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compute_cutoff_window(since_date: str, days_back: int = 7, days_forward: int = 30) -> tuple[str, str]:
    # окно: сегодня-7д, но не раньше since_date (у тебя будет 2026-01-29)
    since = date.fromisoformat(since_date)
    today = datetime.now(timezone.utc).date()
    start = max(since, today - timedelta(days=days_back))
    end = today + timedelta(days=days_forward)
    return (
        iso_z(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)),
        iso_z(datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)),
    )


def build_ms_positions(ms: MSClient, ozon_products: list[dict]) -> list[dict]:
    """
    Позиции без товара пропускаем. Bundle разворачиваем.
    Цена: дефолтная "Цена продажи" из МС (если нашли).
    """
    positions: list[dict] = []
    for p in ozon_products:
        offer_id = str(p.get("offer_id") or "").strip()
        qty = int(p.get("quantity") or 0)
        if not offer_id or qty <= 0:
            continue

        expanded = expand_offer(ms, offer_id, qty)
        for row in expanded:
            meta = row["assortment"]["meta"]
            row_price = None
            try:
                if meta.get("type") == "product":
                    prod = ms._get(meta["href"].replace(ms.base, ""))  # internal
                    row_price = ms.get_sale_price(prod)
                elif meta.get("type") == "bundle":
                    b = ms._get(meta["href"].replace(ms.base, ""))  # internal
                    row_price = ms.get_sale_price(b)
            except Exception:
                row_price = None

            if row_price is not None:
                row["price"] = int(row_price)

            positions.append(row)

    return positions


def ensure_order(ms: MSClient, posting_number: str) -> tuple[str | None, str]:
    """
    Если name=posting_number найден:
      - если метка ozon:<posting_number> есть -> вернуть id
      - иначе -> вернём (None, posting_number+'er...') чтобы создать новый
    """
    found = ms.find_customer_order_by_name(posting_number)
    if found:
        oid = found["id"]
        full = ms.get_customer_order(oid)
        desc = (full.get("description") or "")
        if f"{OZON_MARK}:{posting_number}" in desc:
            return oid, posting_number

        suffix_i = 1
        while True:
            name2 = f"{posting_number}er" if suffix_i == 1 else f"{posting_number}er{suffix_i}"
            exists2 = ms.find_customer_order_by_name(name2)
            if not exists2:
                return None, name2
            suffix_i += 1

    return None, posting_number


def create_order(ms: MSClient, cfg: Config, name: str, posting_number: str, positions: list[dict], dry_run: bool) -> str | None:
    body = {
        "name": name,
        "organization": {"meta": {"href": f"{ms.base}/entity/organization/{cfg.org_id}", "type": "organization", "mediaType": "application/json"}},
        "agent": {"meta": {"href": f"{ms.base}/entity/counterparty/{cfg.agent_id}", "type": "counterparty", "mediaType": "application/json"}},
        "salesChannel": {"meta": {"href": f"{ms.base}/entity/saleschannel/{cfg.sales_channel_id}", "type": "saleschannel", "mediaType": "application/json"}},
        "store": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store", "mediaType": "application/json"}},
        "reserve": True,
        "description": f"{OZON_MARK}:{posting_number}",
        "positions": positions,
    }
    if dry_run:
        log.info("[DRY] create CustomerOrder name=%s positions=%d posting=%s", name, len(positions), posting_number)
        return None
    created = ms.create_customer_order(body)
    return created["id"]


def build_demand_body(ms: MSClient, cfg: Config, customer_order_id: str) -> dict:
    return {
        "organization": {"meta": {"href": f"{ms.base}/entity/organization/{cfg.org_id}", "type": "organization", "mediaType": "application/json"}},
        "agent": {"meta": {"href": f"{ms.base}/entity/counterparty/{cfg.agent_id}", "type": "counterparty", "mediaType": "application/json"}},
        "store": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store", "mediaType": "application/json"}},
        "customerOrder": {"meta": {"href": f"{ms.base}/entity/customerorder/{customer_order_id}", "type": "customerorder", "mediaType": "application/json"}},
    }


def build_move_body(ms: MSClient, cfg: Config, positions: list[dict]) -> dict:
    return {
        "organization": {"meta": {"href": f"{ms.base}/entity/organization/{cfg.org_id}", "type": "organization", "mediaType": "application/json"}},
        "sourceStore": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_ozon_id}", "type": "store", "mediaType": "application/json"}},
        "targetStore": {"meta": {"href": f"{ms.base}/entity/store/{cfg.store_main_id}", "type": "store", "mediaType": "application/json"}},
        "positions": positions,
    }


def _persist(store: StateStore, posting_number: str, ms_order_id: str | None, last_status: str | None,
             demand_created: int, move_created: int, forgotten: int, last_seen_ts: int | None, missed_cycles: int) -> None:
    store.upsert(OrderState(
        posting_number=posting_number,
        ms_order_id=ms_order_id,
        last_status=last_status,
        demand_created=demand_created,
        move_created=move_created,
        forgotten=forgotten,
        last_seen_ts=last_seen_ts,
        missed_cycles=missed_cycles,
    ))


def run_once(cfg: Config, store: StateStore, ozon: OzonClient, ms: MSClient, since_date: str = "2026-01-29") -> None:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    seen_now: set[str] = set()

    cutoff_from, cutoff_to = compute_cutoff_window(since_date, days_back=7, days_forward=30)
    log.info("cutoff window: %s .. %s", cutoff_from, cutoff_to)

    # регулярный опрос только активных
    for status in ("awaiting_packaging", "awaiting_deliver", "delivering"):
        try:
            resp = ozon.unfulfilled_list(cutoff_from, cutoff_to, status=status, limit=50, offset=0)
        except Exception as e:
            log.error("ozon unfulfilled/list status=%s failed: %s", status, e)
            continue

        postings = resp.get("result", {}).get("postings") or resp.get("postings") or []
        for it in postings:
            posting_number = it.get("posting_number") or it.get("postingNumber") or it.get("posting_number")
            if not posting_number:
                continue

            seen_now.add(posting_number)

            s = store.get(posting_number)
            if s.forgotten:
                continue

            try:
                full = ozon.get_posting(posting_number)
            except Exception as e:
                log.error("ozon get posting=%s failed: %s", posting_number, e)
                continue

            posting = full.get("result") or full
            oz_status = (posting.get("status") or "").strip()
            if oz_status not in ALLOWED_OZON_STATUSES:
                continue

            cancellation = posting.get("cancellation") or {}
            initiator = cancellation.get("initiator")
            ms_state_id = ms_state_id_for_ozon_status(oz_status, initiator)

            order_id = s.ms_order_id

            # создаём заказ ТОЛЬКО на awaiting_packaging
            if not order_id and oz_status == "awaiting_packaging":
                existing_id, used_name = ensure_order(ms, posting_number)
                if existing_id:
                    order_id = existing_id
                else:
                    oz_products = posting.get("products") or []
                    positions = build_ms_positions(ms, oz_products)
                    order_id = create_order(ms, cfg, used_name, posting_number, positions, cfg.dry_run)

            if not order_id:
                # не создаём на других статусах — но сохраняем факт статуса
                _persist(store, posting_number, None, oz_status, s.demand_created, s.move_created, s.forgotten, now_ts, 0)
                continue

            # статус в МС
            if ms_state_id and not cfg.dry_run:
                ms.set_order_state(order_id, ms_state_id)

            prev = s.last_status

            # awaiting_deliver -> delivering: Demand один раз, потом забываем
            if prev == "awaiting_deliver" and oz_status == "delivering":
                if not s.demand_created:
                    if cfg.dry_run:
                        log.info("[DRY] create Demand order=%s posting=%s", order_id, posting_number)
                    else:
                        try:
                            ms.create_demand(build_demand_body(ms, cfg, order_id))
                        except Exception as e:
                            log.error("create demand failed posting=%s: %s", posting_number, e)
                    s.demand_created = 1
                s.forgotten = 1

            # если demand уже есть и пришёл delivering — забываем
            if oz_status == "delivering" and s.demand_created:
                s.forgotten = 1

            # сохраняем state + last_seen
            _persist(store, posting_number, order_id, oz_status, s.demand_created, s.move_created, s.forgotten, now_ts, 0)

    # --- ГЛАВНОЕ: ловим отмены/доставку, если заказ пропал из активных
    MISS_THRESHOLD = 2  # 2 цикла подряд нет в активных -> проверяем через get

    for st in store.iter_active():
        if st.forgotten:
            continue
        if st.posting_number in seen_now:
            continue

        st.missed_cycles = (st.missed_cycles or 0) + 1
        if st.missed_cycles < MISS_THRESHOLD:
            st.last_seen_ts = st.last_seen_ts or now_ts
            store.upsert(st)
            continue

        try:
            full = ozon.get_posting(st.posting_number)
            posting = full.get("result") or full
            oz_status = (posting.get("status") or "").strip()

            cancellation = posting.get("cancellation") or {}
            initiator = cancellation.get("initiator")

            if oz_status == "cancelled":
                ms_state_id = ms_state_id_for_ozon_status("cancelled", initiator)

                # 1) статус
                if st.ms_order_id and ms_state_id and not cfg.dry_run:
                    ms.set_order_state(st.ms_order_id, ms_state_id)

                # 2) резерв снять (всегда)
                if st.ms_order_id:
                    if cfg.dry_run:
                        log.info("[DRY] CANCEL posting=%s initiator=%s reserve=false", st.posting_number, initiator)
                    else:
                        try:
                            ms.set_order_reserve(st.ms_order_id, False)
                        except Exception as e:
                            log.error("reserve false failed posting=%s: %s", st.posting_number, e)

                # 3) SELLER -> move (если до этого был awaiting_packaging или awaiting_deliver)
                if (initiator or "").upper() == "SELLER" and st.last_status in ("awaiting_packaging", "awaiting_deliver"):
                    if cfg.dry_run:
                        log.info("[DRY] CANCEL SELLER posting=%s -> MOVE", st.posting_number)
                    else:
                        try:
                            oz_products = posting.get("products") or []
                            positions = build_ms_positions(ms, oz_products)
                            ms.create_move(build_move_body(ms, cfg, positions))
                            st.move_created = 1
                        except Exception as e:
                            log.error("create move failed posting=%s: %s (skip)", st.posting_number, e)

                st.last_status = "cancelled"
                st.forgotten = 1
                st.missed_cycles = 0
                st.last_seen_ts = now_ts
                store.upsert(st)

            elif oz_status == "delivered":
                # delivering -> delivered: просто забываем (и статус обновим)
                ms_state_id = ms_state_id_for_ozon_status("delivered", None)
                if st.ms_order_id and ms_state_id and not cfg.dry_run:
                    ms.set_order_state(st.ms_order_id, ms_state_id)

                st.last_status = "delivered"
                st.forgotten = 1
                st.missed_cycles = 0
                st.last_seen_ts = now_ts
                store.upsert(st)

            else:
                # если всё ещё активный — просто сбросим missed_cycles
                st.missed_cycles = 0
                st.last_seen_ts = now_ts
                store.upsert(st)

        except Exception as e:
            log.error("finalize get failed posting=%s: %s", st.posting_number, e)
            store.upsert(st)
