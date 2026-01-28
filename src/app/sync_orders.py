import logging
from datetime import datetime, timedelta, timezone, date

from app.config import Config
from app.ozon_client import OzonClient
from app.ms_client import MSClient
from app.state_store import StateStore, OrderState
from app.mappers import ALLOWED_OZON_STATUSES, ms_state_id_for_ozon_status
from app.bundle_expand import expand_offer

log = logging.getLogger("sync")

OZON_MARK = "ozon"  # простая метка в description (MVP)

def iso_z(d: datetime) -> str:
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def compute_cutoff_window(since_date: str, days_back: int = 30, days_forward: int = 30) -> tuple[str, str]:
    since = date.fromisoformat(since_date)
    today = datetime.now(timezone.utc).date()
    start = max(since, today - timedelta(days=days_back))
    end = today + timedelta(days=days_forward)
    return iso_z(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)), iso_z(datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc))

def build_ms_positions(ms: MSClient, ozon_products: list[dict]) -> list[dict]:
    """
    ozon_products[]: ожидаем поля offer_id и quantity.
    Позиции без товара пропускаем. Bundle разворачиваем.
    Цена: дефолтная "Цена продажи" из МС. Если цену не нашли — не ставим (МС может ругаться, но часто возьмёт 0).
    """
    positions: list[dict] = []
    for p in ozon_products:
        offer_id = str(p.get("offer_id") or "").strip()
        qty = int(p.get("quantity") or 0)
        if not offer_id or qty <= 0:
            continue

        expanded = expand_offer(ms, offer_id, qty)
        for row in expanded:
            # Попытаемся поставить цену дефолтной продажи
            meta = row["assortment"]["meta"]
            # По meta.type определим entity (product/variant/etc). Для MVP — просто не трогаем если не product/bundle.
            row_price = None
            try:
                if meta.get("type") == "product":
                    prod = ms._get(meta["href"].replace(ms.base, ""))  # internal
                    row_price = ms.get_sale_price(prod)
                elif meta.get("type") == "bundle":
                    b = ms._get(meta["href"].replace(ms.base, ""))
                    row_price = ms.get_sale_price(b)
            except Exception:
                row_price = None

            if row_price is not None:
                row["price"] = int(row_price)
            positions.append(row)

    return positions

def ensure_order(ms: MSClient, posting_number: str, dry_run: bool) -> tuple[str | None, str]:
    """
    Возвращает (order_id, used_name). used_name может быть posting_number или posting_number+'er...'
    """
    found = ms.find_customer_order_by_name(posting_number)
    if found:
        oid = found["id"]
        full = ms.get_customer_order(oid)
        desc = (full.get("description") or "")
        # если наша метка — ok
        if f"{OZON_MARK}:{posting_number}" in desc:
            return oid, posting_number
        # иначе создаём с постфиксом er
        suffix_i = 1
        while True:
            name2 = f"{posting_number}er" if suffix_i == 1 else f"{posting_number}er{suffix_i}"
            exists2 = ms.find_customer_order_by_name(name2)
            if not exists2:
                return None, name2  # создадим новым именем
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
        log.info("[DRY] create CustomerOrder name=%s positions=%d", name, len(positions))
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

def run_once(cfg: Config, store: StateStore, ozon: OzonClient, ms: MSClient, since_date: str = "2026-01-28") -> None:
    cutoff_from, cutoff_to = compute_cutoff_window(since_date, days_back=30, days_forward=30)
    log.info("cutoff window: %s .. %s", cutoff_from, cutoff_to)

    # Берём по статусам отдельно (проще и детерминированно)
    for status in ("awaiting_packaging", "awaiting_deliver", "delivering", "delivered", "cancelled"):
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

            s = store.get(posting_number)
            if s.forgotten:
                continue

            # детальная карточка (чтобы взять товары/инициатор отмены)
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

            # create/find MS order
            order_id = s.ms_order_id
            used_name = posting_number

            if not order_id and oz_status == "awaiting_packaging":
                existing_id, used_name = ensure_order(ms, posting_number, cfg.dry_run)
                if existing_id:
                    order_id = existing_id
                else:
                    oz_products = posting.get("products") or []
                    positions = build_ms_positions(ms, oz_products)
                    order_id = create_order(ms, cfg, used_name, posting_number, positions, cfg.dry_run)
            elif not order_id:
                # не создаём заказ на других статусах
                store.upsert(OrderState(posting_number, None, oz_status, s.demand_created, s.move_created, s.forgotten))
                continue

            # обновление статуса МС
            if ms_state_id and not cfg.dry_run:
                ms.set_order_state(order_id, ms_state_id)

            # обработка переходов/действий
            prev = s.last_status

            # awaiting_deliver -> delivering: Demand один раз, потом забываем
            if prev == "awaiting_deliver" and oz_status == "delivering":
                if not s.demand_created:
                    if cfg.dry_run:
                        log.info("[DRY] create Demand for order=%s posting=%s", order_id, posting_number)
                    else:
                        try:
                            ms.create_demand(build_demand_body(ms, cfg, order_id))
                        except Exception as e:
                            log.error("create demand failed posting=%s: %s", posting_number, e)
                    s.demand_created = 1
                s.forgotten = 1

            # delivering -> delivered: забываем
            if prev == "delivering" and oz_status == "delivered":
                s.forgotten = 1

            # cancelled:
            if oz_status == "cancelled":
                # cancelled after delivering/delivered: update status and forget, demand never deleted
                if prev in ("delivering", "delivered"):
                    s.forgotten = 1
                else:
                    # CLIENT/OZON: снять резерв и забыть
                    if (initiator or "").upper() != "SELLER":
                        if cfg.dry_run:
                            log.info("[DRY] reserve=false order=%s posting=%s", order_id, posting_number)
                        else:
                            try:
                                ms.set_order_reserve(order_id, False)
                            except Exception as e:
                                log.error("reserve false failed posting=%s: %s", posting_number, e)
                        s.forgotten = 1
                    else:
                        # SELLER из awaiting_deliver: reserve=false + Move
                        if prev == "awaiting_deliver":
                            if cfg.dry_run:
                                log.info("[DRY] reserve=false + move for posting=%s", posting_number)
                            else:
                                try:
                                    ms.set_order_reserve(order_id, False)
                                except Exception as e:
                                    log.error("reserve false failed posting=%s: %s", posting_number, e)

                                # move positions = позиции заказа (MVP: строим из Ozon товаров с bundle expand)
                                try:
                                    oz_products = posting.get("products") or []
                                    positions = build_ms_positions(ms, oz_products)
                                    ms.create_move(build_move_body(ms, cfg, positions))
                                    s.move_created = 1
                                except Exception as e:
                                    log.error("create move failed posting=%s: %s (skip)", posting_number, e)
                            s.forgotten = 1
                        else:
                            s.forgotten = 1

            # если demand уже есть и пришёл delivering — забываем
            if oz_status == "delivering" and s.demand_created:
                s.forgotten = 1

            # сохранить state
            store.upsert(OrderState(posting_number, order_id, oz_status, s.demand_created, s.move_created, s.forgotten))
