from config import (
    ORGANIZATION_ID, AGENT_ID,
    SALES_CHANNEL_FBO_ID, STATE_FBO_ID,
    STORE_ID,
    DRY_RUN, OZON_FBO_MARK
)
from ozon_api import get_supply_orders_ids, get_supply_orders_info, get_bundle_items, STATE_CODE
from ms_api import find_customerorder_by_name, create_customerorder
from ms_mapper import build_positions
from logger import log
from datetime import datetime, timedelta, date

def run():
    order_ids = get_supply_orders_ids()
    supplies = get_supply_orders_info(order_ids)
    MIN_DATE = date(2026, 2, 2)
    DAYS_BACK = 10

    cutoff_date = max(
        MIN_DATE,
        date.today() - timedelta(days=DAYS_BACK)
    )

    def parse_created_at(value: str) -> date:
        # Ozon приходит в формате ISO, обычно с Z
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).date()

    before = len(supplies)

    supplies = [
        s for s in supplies
        if s.get("created_at")
        and parse_created_at(s["created_at"]) >= cutoff_date
    ]

    logger.info(
        "Фильтр created_at: было %s, осталось %s (cutoff=%s)",
        before,
        len(supplies),
        cutoff_date.isoformat()
    )

    log.info(f"Найдено FBO-поставок: {len(supplies)}")

    for order in supplies:
        # игнорируем UNSPEC / DATA_FILLING — они и так не в LIST_STATES
        state = order.get("state")

        # CANCELLED — просто забываем поставку
        if state == "CANCELLED":
            log.info(f"Поставка {supply_id} отменена — пропуск")
            continue

        supply = (order.get("supplies") or [None])[0]
        if not supply:
            continue

        supply_id = str(supply["supply_id"])

        # правила на будущее по статусам:
        # - READY_TO_SUPPLY -> создать CustomerOrder
        # - READY -> CANCELLED -> забыть (пока просто не создаём)
        # - READY -> другое -> Demand (потом)

        if state != "READY_TO_SUPPLY":
            # пока только создание заказов по READY
            continue

        existing = find_customerorder_by_name(supply_id)
        if existing:
            desc = existing.get("description", "") or ""
            if OZON_FBO_MARK in desc:
                log.info(f"Заказ {supply_id} уже создан нами — пропуск")
            else:
                log.warning(f"Заказ {supply_id} существует без метки — пропуск")
            continue

        bundle_id = supply.get("bundle_id")
        if not bundle_id:
            log.warning(f"Нет bundle_id для {supply_id}")
            continue

        items = get_bundle_items([bundle_id])
        positions = build_positions(items)

        if not positions:
            log.warning(f"Нет позиций для {supply_id}")
            continue

        payload = {
            "name": supply_id,
            "organization": {"meta": {"href": f"https://api.moysklad.ru/api/remap/1.2/entity/organization/{ORGANIZATION_ID}", "type": "organization", "mediaType": "application/json"}},
            "agent": {"meta": {"href": f"https://api.moysklad.ru/api/remap/1.2/entity/counterparty/{AGENT_ID}", "type": "counterparty", "mediaType": "application/json"}},
            "salesChannel": {"meta": {"href": f"https://api.moysklad.ru/api/remap/1.2/entity/saleschannel/{SALES_CHANNEL_FBO_ID}", "type": "saleschannel", "mediaType": "application/json"}},
            "state": {"meta": {"href": f"https://api.moysklad.ru/api/remap/1.2/entity/customerorder/metadata/states/{STATE_FBO_ID}", "type": "state", "mediaType": "application/json"}},
            "store": {"meta": {"href": f"https://api.moysklad.ru/api/remap/1.2/entity/store/{STORE_ID}", "type": "store", "mediaType": "application/json"}},
            "description": f"{OZON_FBO_MARK}|{supply_id} - {supply['storage_warehouse']['name']}",
            "positions": positions,
        }

        if DRY_RUN:
            log.info(f"[DRY_RUN] Заказ {supply_id} НЕ создан")
            log.debug(payload)
        else:
            log.info(f"Создание заказа {supply_id}")
            create_customerorder(payload)


if __name__ == "__main__":
    run()
