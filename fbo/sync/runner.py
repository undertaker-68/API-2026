from __future__ import annotations

import logging
from datetime import datetime, timezone

from fbo.config import Config
from fbo.ozon.client import OzonClient
from fbo.ozon.supplies import OzonSuppliesApi
from fbo.ms.client import MoySkladClient
from fbo.ms.errors import is_duplicate_number, error_text
from fbo.ms.customer_order import customerorder_find_by_name, customerorder_create
from fbo.ms.move import create_move_with_applicable
from fbo.ms.demand import create_demand_with_applicable
from fbo.ms.find_by_name import find_by_name
from fbo.ms.article_cache import ArticleCache
from fbo.state.store import StateStore
from fbo.state.models import RootState
from fbo.sync.window import compute_window, iso_z
from fbo.sync.mapper import build_positions_from_items, build_customerorder_payload


log = logging.getLogger("fbo.sync")

READY = "READY_TO_SUPPLY"
CANCELLED = "CANCELLED"
OVERDUE = "OVERDUE"

DEMAND_STATUSES = {
    "ACCEPTED_AT_SUPPLY_WAREHOUSE",
    "IN_TRANSIT",
    "ACCEPTANCE_AT_STORAGE_WAREHOUSE",
    "COMPLETED",
    "REJECTED_AT_SUPPLY_WAREHOUSE",
}


def run_once(cfg: Config) -> None:
    oz = OzonClient(cfg.ozon_base_url, cfg.ozon_client_id, cfg.ozon_api_key)
    oz_api = OzonSuppliesApi(oz)

    ms = MoySkladClient(
        cfg.ms_base_url,
        cfg.ms_token,
        rps=cfg.ms_rps,
        retry_max=cfg.ms_retry_max,
        retry_base_seconds=cfg.ms_retry_base_seconds,
    )

    cache = ArticleCache(ms, cfg.ms_article_cache_path)
    cache.load()

    store = StateStore(cfg.state_path)
    state: RootState = store.load()

    since, to = compute_window(cfg.last_days, cfg.min_date_utc)
    log.info("Window: %s .. %s", iso_z(since), iso_z(to))

    supplies = oz_api.list_supply_orders(since, to)
    log.info("Fetched supplies: %d", len(supplies))

    for s in supplies:
        order_id = oz_api.supply_id(s)
        if order_id is None:
            continue

        number = oz_api.supply_number(s)
        status = oz_api.supply_status(s)

        if status == OVERDUE:
            continue

        wh_name = oz_api.destination_warehouse_name(s)
        comment = f"{number} - {wh_name}"
        planned = oz_api.planned_moment(s)

        rec = state.supplies.get(number) or {}

        if rec.get("final") is True:
            rec["updated_at"] = iso_z(datetime.now(timezone.utc))
            state.supplies[number] = rec
            continue

        rec.update(
            {
                "supply_order_id": order_id,
                "last_status": status,
                "warehouse": wh_name,
                "updated_at": iso_z(datetime.now(timezone.utc)),
            }
        )
        state.supplies[number] = rec

        if status == CANCELLED:
            rec["final"] = True
            rec["final_reason"] = "cancelled"
            continue

        def get_positions():
            bundle_items = oz_api.get_supply_items(order_id)
            items = oz_api.extract_items_from_bundle_items(bundle_items)
            positions, missing = build_positions_from_items(cache, items)
            rec["missing_articles"] = missing
            return positions, missing

        # 1) CustomerOrder нужен всегда (даже COMPLETED), если его ещё нет
        existing_co = customerorder_find_by_name(ms, number)
        if existing_co:
            rec["customerorder_exists"] = True
            rec["customerorder_href"] = (existing_co.get("meta") or {}).get("href", "")
        else:
            positions, missing = get_positions()
            payload = build_customerorder_payload(
                supply_number=number,
                comment=comment,
                positions=positions,
                org_id=cfg.ms_org_id,
                agent_id=cfg.ms_agent_id,
                sales_channel_id=cfg.ms_sales_channel_fbo_id,
                state_id=cfg.ms_fbo_state_id,
                store_id=cfg.ms_fbo_demand_store_id,
                planned_moment=planned,
            )

            if cfg.dry_run:
                log.info("[DRY_RUN] Would create CustomerOrder: %s (pos=%d missing=%d)", number, len(positions), len(missing))
            else:
                try:
                    created = customerorder_create(ms, payload)
                    rec["customerorder_created"] = True
                    rec["customerorder_href"] = (created.get("meta") or {}).get("href", "")
                    log.info("Created CustomerOrder: %s", number)
                except Exception as e:
                    if is_duplicate_number(e):
                        rec["final"] = True
                        rec["final_reason"] = "customerorder_duplicate_number"
                        log.warning("CustomerOrder duplicate number => final: %s", number)
                        continue
                    rec["customerorder_error"] = error_text(e)
                    log.exception("CustomerOrder create failed: %s", number)
                    continue

        # 2) Move только на READY
        if status == READY and not rec.get("move_done"):
            positions, _ = get_positions()
            ok, created, reason = create_move_with_applicable(
                ms,
                name=number,
                description=comment,
                org_id=cfg.ms_org_id,
                agent_id=cfg.ms_agent_id,
                state_id=cfg.ms_fbo_move_state_id,
                source_store_id=cfg.ms_fbo_move_source_store_id,
                target_store_id=cfg.ms_fbo_move_target_store_id,
                positions=positions,
                customerorder_href=rec.get("customerorder_href") or None,
                dry_run=cfg.dry_run,
            )

            if reason == "duplicate_number":
                rec["final"] = True
                rec["final_reason"] = "move_duplicate_number"
                log.warning("Move duplicate number => final: %s", number)
                continue

            if ok:
                rec["move_done"] = True
                if created:
                    rec["move_href"] = (created.get("meta") or {}).get("href", "")
                log.info("%s Move: %s", "[DRY_RUN] Would create" if cfg.dry_run else "Created", number)
            else:
                rec["move_error"] = reason
                log.warning("Move not done (%s): %s", reason, number)

        # 3) Demand — для любых статусов кроме CANCELLED/OVERDUE (в т.ч. COMPLETED)
        if status in DEMAND_STATUSES and not rec.get("demand_done"):
            existing_d = find_by_name(ms, "demand", number)
            if existing_d:
                rec["demand_done"] = True
                rec["demand_href"] = (existing_d.get("meta") or {}).get("href", "")
                rec["final"] = True
                rec["final_reason"] = "demand_exists"
                log.info("Demand exists => final: %s", number)
                continue

            positions, _ = get_positions()
            ok, created, reason = create_demand_with_applicable(
                ms,
                name=number,
                description=comment,
                org_id=cfg.ms_org_id,
                agent_id=cfg.ms_agent_id,
                state_id=cfg.ms_fbo_demand_state_id,
                store_id=cfg.ms_fbo_demand_store_id,
                positions=positions,
                customerorder_href=rec.get("customerorder_href") or None,
                dry_run=cfg.dry_run,
            )

            if reason == "duplicate_number":
                rec["final"] = True
                rec["final_reason"] = "demand_duplicate_number"
                log.warning("Demand duplicate number => final: %s", number)
                continue

            if reason == "error_applicable_failed":
                rec["final"] = True
                rec["final_reason"] = "demand_applicable_failed"
                log.warning("Demand applicable failed => final: %s", number)
                continue

            if ok:
                rec["demand_done"] = True
                if created:
                    rec["demand_href"] = (created.get("meta") or {}).get("href", "")
                rec["final"] = True
                rec["final_reason"] = "demand_created"
                log.info("%s Demand => final: %s", "[DRY_RUN] Would create" if cfg.dry_run else "Created", number)
            else:
                rec["demand_error"] = reason
                log.warning("Demand not done (%s): %s", reason, number)

    cache.save()
    store.save(state)
