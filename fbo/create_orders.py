from config import (
    ORGANIZATION_ID, AGENT_ID,
    SALES_CHANNEL_FBO_ID, STATE_FBO_ID,
    STORE_ID,
    DRY_RUN, OZON_FBO_MARK
)
from ozon_api import get_supply_orders_ids, get_supply_orders_info, get_bundle_items
from ms_api import find_customerorder_by_name, create_customerorder
from ms_mapper import build_positions
from logger import log
from datetime import datetime, date


def run():
    order_ids = get_supply_orders_ids()
    supplies = get_supply_orders_info(order_ids)

    # created_at уже приходит из /v3/supply-order/get (см. ozon_api), фильтр по датам там уже на list-этапе
    # здесь можно просто логнуть сколько пришло
    log.info(f"Найдено FBO-поставок (после list/get): {len(supplies)}")

    for order in supplies:
        supply = (order.get("supplies") or [None])[0]
        if not supply:
            continue

        supply_id = str(supply.get("supply_id"))

        state = order.get("state")

        # CANCELLED — просто пропускаем
        if state == "CANCELLED":
            log.info(f"Поставка {supply_id} отменена — пропуск")
            continue

        # пока создаём только READY_TO_SUPPLY
        if state != "READY_TO_SUPPLY":
            continue

        log.info(f"Обработка поставки {supply_id}")

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
            "description": f"{OZON_FBO_MARK}|{supply_id} - {supply.get('storage_warehouse', {}).get('name', '')}",
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
