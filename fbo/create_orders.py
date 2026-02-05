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

logger = log


def run():
    order_ids = get_supply_orders_ids()
    supplies = get_supply_orders_info(order_ids)
    logger.info(f"Найдено FBO-поставок: {len(supplies)}")

    for order in supplies:
        # игнорируем UNSPEC / DATA_FILLING — они и так не в LIST_STATES
        state = order.get("state")

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
                logger.info(f"Заказ {supply_id} уже создан нами — пропуск")
            else:
                logger.warning(f"Заказ {supply_id} существует без метки — пропуск")
            continue

        bundle_id = supply.get("bundle_id")
        if not bundle_id:
            logger.warning(f"Нет bundle_id для {supply_id}")
            continue

        items = get_bundle_items([bundle_id])
        positions = build_positions(items)

        if not positions:
            logger.warning(f"Нет позиций для {supply_id}")
            continue

        payload = {
            "name": supply_id,
            "organization": {"meta": {"type": "organization", "id": ORGANIZATION_ID}},
            "agent": {"meta": {"type": "counterparty", "id": AGENT_ID}},
            "salesChannel": {"meta": {"type": "saleschannel", "id": SALES_CHANNEL_FBO_ID}},
            "state": {"meta": {"type": "state", "id": STATE_FBO_ID}},
            "store": {"meta": {"type": "store", "id": STORE_ID}},
            "moment": order["created_date"],
            "deliveryPlannedMoment": supply["storage_warehouse"]["arrival_date"],
            "description": f"{OZON_FBO_MARK}|{supply_id} - {supply['storage_warehouse']['name']}",
            "positions": positions,
        }

        if DRY_RUN:
            logger.info(f"[DRY_RUN] Заказ {supply_id} НЕ создан")
            logger.debug(payload)
        else:
            logger.info(f"Создание заказа {supply_id}")
            create_customerorder(payload)


if __name__ == "__main__":
    run()
