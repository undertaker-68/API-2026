from __future__ import annotations

import logging
from datetime import datetime, timezone

from fbo.config import Config
from fbo.ozon.client import OzonClient
from fbo.ozon.supplies import OzonSuppliesApi
from fbo.ms.client import MoySkladClient
from fbo.ms.customer_order import customerorder_find_by_name, customerorder_create
from fbo.state.store import StateStore
from fbo.state.models import RootState
from fbo.sync.window import compute_window, iso_z
from fbo.sync.mapper import build_customerorder_payload


log = logging.getLogger("fbo.sync")

# То, что ты уже ловил (плюс UNKNOWN оставим)
FBO_STATUSES_VALID = {
    "READY_TO_SUPPLY",
    "ACCEPTED_AT_SUPPLY_WAREHOUSE",
    "IN_TRANSIT",
    "ACCEPTANCE_AT_STORAGE_WAREHOUSE",
    "COMPLETED",
    "REJECTED_AT_SUPPLY_WAREHOUSE",
    "CANCELLED",
    "OVERDUE",
    "UNKNOWN",
}


def run_once(cfg: Config) -> None:
    oz = OzonClient(cfg.ozon_base_url, cfg.ozon_client_id, cfg.ozon_api_key)
    oz_api = OzonSuppliesApi(oz)

    ms = MoySkladClient(cfg.ms_base_url, cfg.ms_token)

    store = StateStore(cfg.state_path)
    state: RootState = store.load()

    since, to = compute_window(cfg.last_days, cfg.min_date_utc)
    log.info("Window: %s .. %s", iso_z(since), iso_z(to))

    # list_supplies теперь ждёт datetime UTC
    supplies = oz_api.list_supply_orders(since, to)

    log.info("Fetched supplies: %d", len(supplies))

    for s in supplies:
        supply_order_id = oz_api.supply_id(s)
        if supply_order_id is None:
            continue

        number = oz_api.supply_number(s)
        status = oz_api.supply_status(s)
        wh_name = oz_api.warehouse_name(s)

        if status not in FBO_STATUSES_VALID:
            log.debug("Skip supply %s: status=%s", number, status)
            continue

        rec = state.supplies.get(number) or {}
        rec.update(
            {
                "supply_order_id": supply_order_id,
                "last_status": status,
                "warehouse": wh_name,
                "updated_at": iso_z(datetime.now(timezone.utc)),
            }
        )
        state.supplies[number] = rec

        # 1) Если документ уже есть — пропускаем создание, но статус/rec обновляем
        existing = customerorder_find_by_name(ms, number)
        if existing:
            rec["ms_exists"] = True
            rec["ms_customerorder_href"] = (existing.get("meta") or {}).get("href", "")
            log.info("MS order exists, skip create: %s (status=%s)", number, status)
            continue

        # 2) Берём состав поставки
        bundle_items = oz_api.get_supply_items(supply_order_id)
        items = oz_api.extract_items_from_bundle_items(bundle_items)

        if not items:
            rec["skip_reason"] = "no_items"
            log.info("No items for supply %s, skip create", number)
            continue

        payload = build_customerorder_payload(
            ms=ms,
            supply_number=number,
            warehouse_name=wh_name,
            items=items,
            org_id=cfg.ms_org_id,
            agent_id=cfg.ms_agent_id,
            sales_channel_id=cfg.ms_sales_channel_fbo_id,
            state_id=cfg.ms_fbo_state_id,
        )

        if not payload.get("positions"):
            rec["skip_reason"] = "no_positions"
            log.info("No valid MS positions for supply %s, skip create", number)
            continue

        # 3) Создание (или dry-run)
        if cfg.dry_run:
            rec["dry_run"] = True
            rec["ms_created"] = False
            log.info("[DRY_RUN] Would create MS CustomerOrder: %s (positions=%d)", number, len(payload["positions"]))
            continue

        created = customerorder_create(ms, payload)
        rec["ms_created"] = True
        rec["ms_customerorder_href"] = (created.get("meta") or {}).get("href", "")
        log.info("Created MS CustomerOrder: %s", number)

    store.save(state)
