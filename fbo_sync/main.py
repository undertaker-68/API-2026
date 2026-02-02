from __future__ import annotations
import os
import time
import math
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, Any, List, Tuple

from .settings import (
    POLL_SECONDS, calc_window,
    STORE_MAIN_ID, STORE_FBO_ID,
    MOVE_STATE_ID, DEMAND_STATE_ID,
    STATE_READY_TO_SUPPLY, STATE_CANCELLED,
)
from .ozon_fbo import OzonFboClient
from .ms_api import MoySkladClient, MoySkladError
from .state import StateStore, SupplyState

from dataclasses import dataclass

@dataclass(frozen=True)
class Cfg:
    ozon_client_id: str
    ozon_api_key: str
    ms_token: str
    ms_base_url: str
    org_id: str
    agent_id: str
    sales_channel_id: str
    dry_run: bool

def load_cfg_from_env() -> Cfg:
    def must(k: str) -> str:
        v = os.getenv(k)
        if not v:
            raise RuntimeError(f"Missing env {k}")
        return v

    return Cfg(
        ozon_client_id=must("OZON_CLIENT_ID"),
        ozon_api_key=must("OZON_API_KEY"),
        ms_token=must("MS_TOKEN"),
        ms_base_url=os.getenv("MS_BASE_URL", "https://api.moysklad.ru/api/remap/1.2"),
        org_id=must("MS_ORG_ID"),
        agent_id=must("MS_AGENT_ID"),
        sales_channel_id=os.getenv("MS_SALES_CHANNEL_ID_FBO") or must("MS_SALES_CHANNEL_ID"),
        dry_run=os.getenv("DRY_RUN", "0") == "1",
    )

def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

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

def expand_ms_bundles(ms: MoySkladClient, offer_qty: Dict[str, int]) -> Dict[str, float]:
    """
    Вход: offer_id(article) -> qty
    Выход: article (уже товара/компонента) -> qty
    """
    out: Dict[str, float] = defaultdict(float)

    for offer_id, qty in offer_qty.items():
        # сначала пробуем bundle
        b = ms.get_bundle_by_article(offer_id)
        if b:
            bundle_id = b["id"]
            comps = ms.get_bundle_components(bundle_id)
            total_components = 0.0
            for comp_meta, comp_qty in comps:
                # comp_meta -> entity type определить по href не будем, просто шлём meta
                # но нам нужен article компонента: дотягиваем сущность не хотим -> используем meta напрямую в позициях
                # поэтому ниже делаем спец: складываем по href, а не по article
                # Упрощение: в позициях МС будем использовать assortment.meta прямо (это корректно)
                href = comp_meta["href"]
                out[href] += comp_qty * qty
                total_components += comp_qty * qty

            # спец-исключение offer_id=00233
            if offer_id == "00233":
                add_qty = math.floor(total_components / 5.0)
                if add_qty > 0:
                    p = ms.get_product_by_article("00651") or ms.get_bundle_by_article("00651")
                    if p:
                        href = p["meta"]["href"] if "meta" in p else p["meta"]["href"]
                        out[href] += add_qty
            continue

        # иначе обычный product
        p = ms.get_product_by_article(offer_id)
        if not p:
            # если нет в МС — пропускаем позицию
            continue
        out[p["meta"]["href"]] += qty

    return dict(out)

def ms_positions_from_hrefs(ms_qty_by_href: Dict[str, float]) -> List[Dict[str, Any]]:
    res = []
    for href, qty in ms_qty_by_href.items():
        res.append({
            "assortment": {"meta": {"href": href, "type": "assortment", "mediaType": "application/json"}},
            "quantity": qty,
        })
    return res

def main():
    cfg = load_cfg_from_env()
    oz = OzonFboClient(cfg.ozon_client_id, cfg.ozon_api_key)
    ms = MoySkladClient(cfg.ms_base_url, cfg.ms_token)
    state = StateStore(path=os.path.join(os.path.dirname(__file__), "state.json"))

    while True:
        now = datetime.now(timezone.utc)
        w = calc_window(now)
        since, to = iso(w.since), iso(w.to)

        # Берём кандидатов: READY и CANCELLED (для переходов)
        ids = set()
        for st in (STATE_READY_TO_SUPPLY, STATE_CANCELLED):
            for oid in oz.list_order_ids(since, to, st, sort_by=1, limit=50):
                ids.add(int(oid))

        # GET пачками до 50
        ids_list = sorted(ids)
        for i in range(0, len(ids_list), 50):
            batch = ids_list[i:i+50]
            orders = oz.get_orders(batch)

            for o in orders:
                order_number = str(o["order_number"]).strip()
                cur_state = str(o.get("state") or "").strip()

                st = state.get(order_number)

                # если в МС уже есть любой документ с таким name (order), пропускаем всю поставку (как ты хотел)
                if ms.find_by_name("customerorder", order_number) or ms.find_by_name("move", order_number) or ms.find_by_name("demand", order_number):
                    st.order_done = True
                    st.move_done = True
                    st.demand_done = True
                    st.last_state = cur_state
                    state.set(order_number, st)
                    continue

                # соберём bundle_id из всех supplies
                supplies = o.get("supplies", []) or []
                bundle_ids = [s.get("bundle_id") for s in supplies if s.get("bundle_id")]
                offer_qty = aggregate_ozon_positions(oz, bundle_ids)
                ms_qty_by_href = expand_ms_bundles(ms, offer_qty)
                positions = ms_positions_from_hrefs(ms_qty_by_href)

                # 1) CustomerOrder создаём при READY_TO_SUPPLY
                if cur_state == "READY_TO_SUPPLY" and not st.order_done:
                    body = {
                        "name": order_number,
                        "organization": ms.mk_ref("organization", cfg.org_id),
                        "agent": ms.mk_ref("counterparty", cfg.agent_id),
                        "salesChannel": ms.mk_ref("saleschannel", cfg.sales_channel_id),
                        "positions": positions,
                        "reserve": True,
                    }
                    try:
                        if not cfg.dry_run:
                            ms.create_customer_order(body)
                        st.order_done = True
                    except MoySkladError:
                        # если заказ не создался — пропускаем поставку до следующего цикла
                        pass

                # 2) Move при READY_TO_SUPPLY (с retry applicable true -> false)
                if cur_state == "READY_TO_SUPPLY" and not st.move_done:
                    body = {
                        "name": order_number,
                        "organization": ms.mk_ref("organization", cfg.org_id),
                        "sourceStore": ms.mk_ref("store", STORE_MAIN_ID),
                        "targetStore": ms.mk_ref("store", STORE_FBO_ID),
                        "state": ms.mk_ref("state", MOVE_STATE_ID),
                        "positions": positions,
                    }
                    try:
                        if cfg.dry_run:
                            st.move_done = True
                        else:
                            created = ms.try_create_move_with_fallback(body)
                            if created is not None:
                                st.move_done = True
                            else:
                                # конфликт номера -> пропускаем всю поставку (как ты сказал)
                                st.move_done = True
                    except MoySkladError:
                        # прочие ошибки — попробуем в следующем цикле
                        pass

                # 3) Demand при выходе из READY_TO_SUPPLY на любой другой, кроме CANCELLED
                if st.last_state == "READY_TO_SUPPLY" and cur_state not in ("READY_TO_SUPPLY", "CANCELLED") and not st.demand_done:
                    body = {
                        "name": order_number,
                        "organization": ms.mk_ref("organization", cfg.org_id),
                        "agent": ms.mk_ref("counterparty", cfg.agent_id),
                        "store": ms.mk_ref("store", STORE_FBO_ID),
                        "state": ms.mk_ref("state", DEMAND_STATE_ID),
                        "positions": positions,
                    }
                    try:
                        if not cfg.dry_run:
                            ms.create_demand(body)
                        st.demand_done = True
                    except MoySkladError:
                        # если demand не сохранить — пропускаем (как ты требовал)
                        st.demand_done = True

                st.last_state = cur_state
                state.set(order_number, st)

        state.save()
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
