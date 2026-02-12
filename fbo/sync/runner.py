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
IGNORED = {"UNSPECIFIED", "DATA_FILLING", "ORDER_STATE_UNSPECIFIED", "ORDER_STATE_DATA_FILLING"}


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
        wh_name = oz_api.warehouse_name(s)
        planned = getattr(oz_api, "planned_moment", lambda _x: None)(s)
        comment = f"{number} - {wh_name}"

        rec = state.supplies.get(number) or {}

        try:
            log.info("SUPPLY start number=%s status=%s", number, status)

            if rec.get("final") is True:
                log.info("SUPPLY skip number=%s reason=%s", number, rec.get("final_reason"))
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
                log.info("SUPPLY final number=%s reason=cancelled", number)
                continue

            if status in IGNORED:
                rec["final"] = True
                rec["final_reason"] = f"ignored_state:{status}"
                log.info("SUPPLY final number=%s reason=ignored_state:%s", number, status)
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
                    if missing:
                        log.warning("SUPPLY number=%s missing_articles=%s", number, missing)

                    positions_cache[number] = (positions, missing)
                    return positions, missing

                except requests.HTTPError as e:
                    resp = getattr(e, "response", None)
                    code = getattr(resp, "status_code", None)

                    rec["ozon_bundle_last_error"] = str(e)

                    if code == 429:
                        log.warning("SUPPLY skip number=%s reason=ozon_bundle_429", number)
                        return None

                    log.warning("SUPPLY skip number=%s reason=ozon_bundle_http_%s", number, code)
                    return None
                except Exception as e:
                    rec["ozon_bundle_last_error"] = str(e)
                    log.warning("SUPPLY skip number=%s reason=ozon_bundle_error err=%s", number, e)
                    return None

            # ===================== CustomerOrder =====================
            if not rec.get("customerorder_exists") and not rec.get("customerorder_created"):
                existing_co = customerorder_find_by_name(ms, number)
                if existing_co:
                    rec["customerorder_exists"] = True
                    rec["customerorder_href"] = (existing_co.get("meta") or {}).get("href", "")
                else:
                    gp = get_positions()
                    if gp is None:
                        log.warning("SUPPLY skip number=%s reason=no_positions (bundle/get error)", number)
                        continue

                    positions, missing = gp

                    if not positions:
                        log.warning("SUPPLY skip number=%s reason=empty_positions", number)
                        continue

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
                        log.info("[DRY_RUN] Would create CustomerOrder: %s", number)
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

            # ===================== Move =====================
            if status == READY and not rec.get("move_done"):
                gp = get_positions()
                if gp is None:
                    log.warning("SUPPLY skip number=%s reason=no_positions (bundle/get error)", number)
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

                if ok:
                    rec["move_done"] = True
                    log.info("Move done: %s", number)

            # ===================== Demand =====================
            if not rec.get("demand_done"):
                if status == READY:
                    pass
                else:
                    existing_d = find_by_name(ms, "demand", number)
                    if existing_d:
                        rec["demand_done"] = True
                        rec["final"] = True
                        rec["final_reason"] = "demand_exists"
                        log.info("Demand exists => final: %s", number)
                        continue

                    gp = get_positions()
                    if gp is None:
                        log.warning("SUPPLY skip number=%s reason=no_positions (bundle/get error)", number)
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

                    if ok:
                        rec["demand_done"] = True
                        rec["final"] = True
                        rec["final_reason"] = "demand_done"
                        log.info("Demand created => final: %s", number)

        except Exception as e:
            rec["last_error"] = error_text(e)
            log.exception("SUPPLY FAILED number=%s status=%s", number, status)
            state.supplies[number] = rec
            continue

    store.save(state)
