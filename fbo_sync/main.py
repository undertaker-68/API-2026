from __future__ import annotations

import time
import os
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, Any, List, Tuple

from fbo_sync.settings import (
    Settings,
    POLL_SECONDS, calc_window,
    STORE_MAIN_ID, STORE_FBO_ID,
    MOVE_STATE_ID, DEMAND_STATE_ID,
    STATE_READY_TO_SUPPLY, STATE_CANCELLED,
)
from fbo_sync.ozon_fbo import OzonFboClient
from fbo_sync.ms_api import MoySkladClient, MoySkladError
from fbo_sync.state import StateStore, SupplyState


def iso_date_only(z_dt: str) -> str:
    # "2026-02-09T11:00:00Z" -> "2026-02-09"
    if not z_dt:
        return ""
    return z_dt.split("T", 1)[0]


def aggregate_ozon_positions(oz: OzonFboClient, bundle_ids: List[str]) -> Dict[str, int]:
    # offer_id -> qty
    agg: Dict[str, int] = defaultdict(int)
    for bid in bundle_ids:
        for it in oz.iter_bundle_items(bid):
            offer_id = str(it.get("offer_id", "")).strip()
            qty = int(it.get("quantity") or 0)
            if offer_id and qty > 0:
                agg[offer_id] += qty
    return dict(agg)


def expand_ms_bundles_to_components(ms: MoySkladClient, offer_qty: Dict[str, int]) -> List[Tuple[Dict[str, Any], float]]:
    """
    Вход: offer_id(article) -> qty (из Ozon)
    Выход: [(assortment_meta_компонента_или_товара, qty), ...]
    ВАЖНО: bundle всегда разворачиваем в компоненты.
    """
    out: Dict[str, float] = defaultdict(float)  # href -> qty
    href_meta: Dict[str, Dict[str, Any]] = {}

    for article, qty in offer_qty.items():
        row = ms.get_assortment_by_article(article)
        if not row:
            continue

        meta = row["meta"]
        href = meta["href"]
        typ = meta.get("type")

        if typ == "bundle":
            bundle_id = row["id"]
            comps = ms.get_bundle_components(bundle_id)
            for comp_meta, comp_qty in comps:
                chref = comp_meta["href"]
                out[chref] += float(qty) * float(comp_qty)
                href_meta[chref] = comp_meta
        else:
            out[href] += float(qty)
            href_meta[href] = meta

    # превращаем в список позиций
    res: List[Tuple[Dict[str, Any], float]] = []
    for href, q in out.items():
        if q <= 0:
            continue
        res.append((href_meta[href], q))
    return res


def build_positions_with_prices(ms: MoySkladClient, items: List[Tuple[Dict[str, Any], float]]) -> List[Dict[str, Any]]:
    """
    items: [(assortment_meta, qty), ...]
    ставим цену продажи МС в копейках в поле price
    """
    pos: List[Dict[str, Any]] = []
    for meta, qty in items:
        href = meta["href"]
        price = ms.get_sale_price_by_href(href)
        pos.append(
            {
                "assortment": {"meta": meta},
                "quantity": float(qty),
                "price": int(price),
            }
        )
    return pos


def main() -> None:
    stg = Settings.from_env()

    oz = OzonFboClient(stg.ozon_client_id, stg.ozon_api_key)
    ms = MoySkladClient(stg.ms_base_url, stg.ms_token)

    state = StateStore("fbo_sync/state.json")

    while True:
        now = datetime.now(timezone.utc)
        since, to = calc_window(now, hours_back=48)

        # берём READY_TO_SUPPLY (states:[2] у вас в curl) — тут уже в ozon_fbo сделано
        orders = oz.list_supply_orders(since=since, to=to)

        for o in orders:
            order_number = str(o["order_number"])  # это "2000041728589"
            cur_state = str(o.get("state") or "")

            st = state.get(order_number) or SupplyState()

            # timeslot -> план дата отгрузки
            timeslot_from = (
                (o.get("timeslot") or {}).get("timeslot") or {}
            ).get("from") or ""
            planned_date = iso_date_only(timeslot_from)  # YYYY-MM-DD
            delivery_planned = f"{planned_date} 00:00:00.000" if planned_date else None

            # comment: <order_number> - <storage_warehouse/name>
            wh_name = ""
            try:
                supplies = (o.get("supplies") or [])
                if supplies:
                    wh_name = ((supplies[0].get("storage_warehouse") or {}).get("name") or "")
            except Exception:
                pass
            comment = f"{order_number} - {wh_name}".strip(" -")

            # позиции
            bundle_ids = [s.get("bundle_id") for s in (o.get("supplies") or []) if s.get("bundle_id")]
            offer_qty = aggregate_ozon_positions(oz, bundle_ids)
            expanded = expand_ms_bundles_to_components(ms, offer_qty)
            positions = build_positions_with_prices(ms, expanded)

            # если позиций нет — смысла создавать пустые документы нет
            if not positions:
                st.last_state = cur_state
                state.set(order_number, st)
                continue

            # 1) CustomerOrder (всегда для READY_TO_SUPPLY)
            if cur_state == STATE_READY_TO_SUPPLY and not st.order_done:
                body = {
                    "name": order_number,
                    "organization": ms.mk_ref("organization", stg.org_id),
                    "agent": ms.mk_ref("counterparty", stg.agent_id),
                    "store": ms.mk_ref("store", STORE_FBO_ID),
                    "salesChannel": ms.mk_ref("saleschannel", stg.sales_channel_id),
                    "positions": positions,
                    "reserve": True,
                    "description": comment,
                }
                if delivery_planned:
                    body["deliveryPlannedMoment"] = delivery_planned

                if stg.customerorder_state_id:
                    body["state"] = ms.mk_doc_state_ref("customerorder", stg.customerorder_state_id)

                try:
                    if not stg.dry_run:
                        ms.create_customer_order(body)
                    st.order_done = True
                except MoySkladError:
                    pass

            # 2) Move (если нужен для логики FBO — оставляю как было)
            if cur_state == STATE_READY_TO_SUPPLY and not st.move_done:
                body = {
                    "name": order_number,
                    "organization": ms.mk_ref("organization", stg.org_id),
                    "sourceStore": ms.mk_ref("store", STORE_MAIN_ID),
                    "targetStore": ms.mk_ref("store", STORE_FBO_ID),
                    "positions": positions,
                    "description": comment,
                }
                if MOVE_STATE_ID:
                    body["state"] = ms.mk_doc_state_ref("move", MOVE_STATE_ID)

                try:
                    if stg.dry_run:
                        st.move_done = True
                    else:
                        ms.try_create_move_with_fallback(body)
                        st.move_done = True
                except MoySkladError:
                    pass

            # 3) Demand (отгрузка) — при выходе из READY_TO_SUPPLY
            if (
                st.last_state == STATE_READY_TO_SUPPLY
                and cur_state not in (STATE_READY_TO_SUPPLY, STATE_CANCELLED)
                and not st.demand_done
            ):
                # найдём заказ, чтобы привязать
                co = None
                try:
                    co = ms.find_by_name("customerorder", order_number)
                except Exception:
                    co = None

                body = {
                    "name": order_number,
                    "organization": ms.mk_ref("organization", stg.org_id),
                    "agent": ms.mk_ref("counterparty", stg.agent_id),
                    "store": ms.mk_ref("store", STORE_FBO_ID),
                    "positions": positions,
                    "description": comment,
                }
                if co and co.get("meta"):
                    body["customerOrder"] = {"meta": co["meta"]}

                if DEMAND_STATE_ID:
                    body["state"] = ms.mk_doc_state_ref("demand", DEMAND_STATE_ID)

                try:
                    if not stg.dry_run:
                        ms.create_demand(body)
                    st.demand_done = True
                except MoySkladError:
                    st.demand_done = True

            st.last_state = cur_state
            state.set(order_number, st)

        state.save()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
