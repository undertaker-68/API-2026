from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, List

import requests

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

    hist: dict[str, int] = {}
    for s in supplies:
        st = oz_api.supply_status(s)
        hist[st] = hist.get(st, 0) + 1
    log.info("Status histogram: %s", hist)

    for s in supplies:
        order_id = oz_api.supply_id(s)
        if order_id is None:
            continue

        number = oz_api.supply_number(s)
        status = oz_api.supply_status(s)

        # ✅ правильный склад назначения (storage_warehouse.name)
        wh_name = oz_api.warehouse_name(s)

        # ✅ правильная план-дата (arrival_date)
        planned = oz_api.planned_moment(s)

        # ✅ правильный комментарий
        comment = f"{number} - {wh_name}"

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

        positions_cache: dict[str, Tuple[List[dict], List[str]]] = {}

        def get_positions() -> Optional[Tuple[List[dict], List[str]]]:
            if number in positions_cache:
                return positions_cache[number]
            try:
                bundle_items = oz_api.get_supply_items(order_id)
                items = oz_api.extract_items_from_bundle_items(bundle_items)
                positions, missing = build_positions_from_items(cache, items)
                rec["missing_articles"] = missing
                positions_cache[number] = (positions, missing)
                return positions, missing
            except requests.HTTPError as e:
                resp = getattr(e, "response", None)
                if resp is not None and resp.status_code == 429:
                    rec["ozon_bundle_rate_limited"] = True
                    rec["ozon_bundle_last_error"] = str(e)
                    log.warning("Ozon bundle 429, retry next cycle: %s", number)
                    return None
                rec["ozon_bundle_last_error"] = str(e)
                raise

        # ========== CustomerOrder ==========
        if not rec.get("customerorder_exists") and not rec.get("customerorder_created"):
            existing_co = customerorder_find_by_name(ms, number)
            if existing_co:
                rec["customerorder_exists"] = True
                rec["customerorder_href"] = (existing_co.get("meta") or {}).get("href", "")
            else:
                gp = get_positions()
                if gp is None:
                    continue
                positions, missing = gp

                payload = build_customerorder_payload(
                    supply_number=number,
                    comment=comment,
                    positions=positions,
                    org_id=cfg.ms_org_id,
                    agent_id=cfg.ms_agent_id,
                    sales_channel_id=cfg.ms_sales_channel_fbo_id,
                    state_id=cfg.ms_fbo_state_id,
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
                            continue
                        rec["customerorder_error"] = error_text(e)
                        continue

        co_href = rec.get("customerorder_href") or None

        # ========== Move only on READY ==========
        if status == READY and not rec.get("move_done"):
            gp = get_positions()
            if gp is None:
                continue
            positions, _ = gp

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
                customerorder_href=co_href,
                dry_run=cfg.dry_run,
            )

            if reason == "duplicate_number":
                rec["final"] = True
                rec["final_reason"] = "move_duplicate_number"
                continue

            if ok:
                rec["move_done"] = True
                if created:
                    rec["move_href"] = (created.get("meta") or {}).get("href", "")
                log.info("%s Move: %s", "[DRY_RUN] Would create" if cfg.dry_run else "Done", number)
            else:
                rec["move_done"] = False
                rec["move_error"] = reason

        # ========== Demand for ANY status except CANCELLED ==========
        if not rec.get("demand_done"):
            existing_d = find_by_name(ms, "demand", number)
            if existing_d:
                rec["demand_done"] = True
                rec["demand_href"] = (existing_d.get("meta") or {}).get("href", "")
                rec["final"] = True
                rec["final_reason"] = "demand_exists"
                continue

            gp = get_positions()
            if gp is None:
                continue
            positions, _ = gp

            ok, created, reason = create_demand_with_applicable(
                ms,
                name=number,
                description=comment,
                org_id=cfg.ms_org_id,
                agent_id=cfg.ms_agent_id,
                state_id=cfg.ms_fbo_demand_state_id,
                store_id=cfg.ms_fbo_demand_store_id,
                positions=positions,
                customerorder_href=co_href,
                dry_run=cfg.dry_run,
            )

            if reason in ("duplicate_number", "error_applicable_failed"):
                rec["final"] = True
                rec["final_reason"] = reason
                continue

            if ok:
                rec["demand_done"] = True
                if created:
                    rec["demand_href"] = (created.get("meta") or {}).get("href", "")
                rec["final"] = True
                rec["final_reason"] = "demand_done"
                log.info("%s Demand => final: %s", "[DRY_RUN] Would create" if cfg.dry_run else "Created", number)

    store.save(state)
    cache.save()
