from config import (
    ORGANIZATION_ID, AGENT_ID,
    SALES_CHANNEL_FBO_ID, STATE_FBO_ID,
    STORE_ID,
    DRY_RUN, OZON_FBO_MARK
)
from ozon_api import get_supplies, get_bundle_items
from ms_api import find_customerorder_by_name, create_customerorder
from ms_mapper import build_positions
from logger import log


def run():
    supplies = get_supplies()
    log.info(f"Найдено FBO-поставок: {len(supplies)}")

    for order in supplies:
        supply = order["supplies"][0]
        supply_id = str(supply["supply_id"])

        log.info(f"Обработка поставки {supply_id}")

        existing = find_customerorder_by_name(supply_id)
        if existing:
            desc = existing.get("description", "")
            if OZON_FBO_MARK in desc:
                log.info(f"Заказ {supply_id} уже создан нами — пропуск")
            else:
                log.warning(f"Заказ {supply_id} существует без метки — пропуск")
            continue

        items = get_bundle_items([supply["bundle_id"]])
        log.debug(f"Ozon позиции: {items}")

        positions = build_positions(items)
        if not positions:
            log.warning(f"Нет позиций для {supply_id}")
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
            log.info(f"[DRY_RUN] Заказ {supply_id} НЕ создан")
            log.debug(payload)
        else:
            log.info(f"Создание заказа {supply_id}")
            create_customerorder(payload)


if __name__ == "__main__":
    run()
