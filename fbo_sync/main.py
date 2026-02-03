from __future__ import annotations

from dataclasses import dataclass
import os
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from fbo_sync.ozon_fbo import OzonFBO
from fbo_sync.ms_api import MoySkladClient, MoySkladError
from fbo_sync.settings import Settings


@dataclass
class OrderState:
    order_done: bool = False
    move_done: bool = False
    demand_done: bool = False
    last_state: str = ""


class StateStore:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, OrderState] = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in raw.items():
                self.data[k] = OrderState(**v)
        except FileNotFoundError:
            self.data = {}

    def save(self) -> None:
        raw = {k: vars(v) for k, v in self.data.items()}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get(self, order_number: str) -> OrderState:
        if order_number not in self.data:
            self.data[order_number] = OrderState()
        return self.data[order_number]


def load_cfg_from_env() -> Settings:
    def must(k: str) -> str:
        v = os.getenv(k)
        if not v:
            raise RuntimeError(f"Missing env {k}")
        return v

    return Settings(
        ozon_client_id=must("OZON_CLIENT_ID"),
        ozon_api_key=must("OZON_API_KEY"),
        ms_token=must("MS_TOKEN"),
        ms_base_url=os.getenv("MS_BASE_URL", "https://api.moysklad.ru/api/remap/1.2"),
        dry_run=os.getenv("DRY_RUN", "0") == "1",
        poll_seconds=int(os.getenv("POLL_SECONDS", "60")),
        ms_org_id=must("MS_ORG_ID"),
        ms_agent_id=must("MS_AGENT_ID"),
        ms_sales_channel_id=must("MS_SALES_CHANNEL_ID"),
    )


def aggregate_ozon_positions(oz: OzonFBO, bundle_ids: List[str]) -> Dict[str, float]:
    offer_qty: Dict[str, float] = {}
    for bid in bundle_ids:
        for it in oz.iter_bundle_items(bid):
            offer = str(it.get("offer_id") or "").strip()
            qty = float(it.get("quantity") or 0)
            if not offer or qty <= 0:
                continue
            offer_qty[offer] = offer_qty.get(offer, 0) + qty
    return offer_qty


def expand_ms_bundles(ms: MoySkladClient, offer_qty: Dict[str, float]) -> Dict[str, float]:
    """
    На вход: {offer_id(article): qty}
    На выход: {assortment.meta.href: qty}
    """
    out: Dict[str, float] = {}

    for offer_id, qty in offer_qty.items():
        a = ms.get_assortment_by_article(offer_id)
        if not a:
            continue

        meta = a.get("meta") or {}
        href = meta.get("href")
        typ = meta.get("type")

        if not href or not typ:
            continue

        if typ == "bundle":
            bundle_id = a.get("id")
            comps = ms.get_bundle_components(bundle_id)

            total_components_qty = 0.0
            for comp_meta, comp_qty_in_bundle in comps:
                comp_href = comp_meta.get("href")
                if not comp_href:
                    continue
                comp_total = qty * float(comp_qty_in_bundle)
                total_components_qty += comp_total
                out[comp_href] = out.get(comp_href, 0) + comp_total

            # спец-исключение
            # если offer_id == "00233" и он bundle — добавляем article=00651 qty = total_components/5
            if offer_id == "00233":
                extra = ms.get_assortment_by_article("00651")
                if extra and (extra.get("meta") or {}).get("href"):
                    extra_href = extra["meta"]["href"]
                    out[extra_href] = out.get(extra_href, 0) + (total_components_qty / 5.0)

        else:
            out[href] = out.get(href, 0) + qty

    return out


def ms_positions_from_hrefs(ms: MoySkladClient, ms_qty_by_href: Dict[str, float]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for href, qty in ms_qty_by_href.items():
        if not qty:
            continue
        meta_type = href.split("/entity/")[1].split("/")[0] if "/entity/" in href else "assortment"
        price = ms.get_sale_price(href)
        rows.append(
            {
                "assortment": {"meta": {"href": href, "type": meta_type, "mediaType": "application/json"}},
                "quantity": qty,
                "price": price,
            }
        )
    return rows


def day_from_iso_z(s: str) -> str:
    # "2026-02-09T11:00:00Z" -> "2026-02-09 00:00:00.000"
    dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d 00:00:00.000")


def main() -> None:
    cfg = load_cfg_from_env()
    oz = OzonFBO("https://api-seller.ozon.ru", cfg.ozon_client_id, cfg.ozon_api_key)
    ms = MoySkladClient(cfg.ms_base_url, cfg.ms_token)

    state = StateStore("fbo_sync/state.json")

    # окно: последние 2 суток (как у тебя сейчас)
    since = (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    while True:
        order_ids = oz.list_orders(since=since, to=to, states=[2], limit=50)
        if not order_ids:
            state.save()
            import time as _t
            _t.sleep(cfg.poll_seconds)
            continue

        orders = oz.get_orders(order_ids)

        for o in orders:
            order_number = str(o.get("order_number") or "").strip()
            if not order_number:
                continue

            st = state.get(order_number)

            # если в памяти отмечено "сделано", но документ(ы) в МС удалили руками — нужно пересоздать
            ms_order = ms.find_by_name("customerorder", order_number)
            ms_move = ms.find_by_name("move", order_number)
            ms_demand = ms.find_by_name("demand", order_number)
            if st.order_done and not ms_order:
                st.order_done = False
            if st.move_done and not ms_move:
                st.move_done = False
            if st.demand_done and not ms_demand:
                st.demand_done = False

            state_name = str(o.get("state") or "")
            st.last_state = state_name

            supplies = o.get("supplies") or []
            bundle_ids = [s.get("bundle_id") for s in supplies if s.get("bundle_id")]

            if not bundle_ids:
                continue

            offer_qty = aggregate_ozon_positions(oz, bundle_ids)
            ms_qty_by_href = expand_ms_bundles(ms, offer_qty)
            positions = ms_positions_from_hrefs(ms, ms_qty_by_href)

            # Плановая дата отгрузки = timeslot.from (дата, без времени)
            timeslot_from = (((o.get("timeslot") or {}).get("timeslot") or {}).get("from")) or ""
            planned = day_from_iso_z(timeslot_from) if timeslot_from else None

            storage_name = ""
            try:
                storage_name = str((supplies[0].get("storage_warehouse") or {}).get("name") or "")
            except Exception:
                pass

            description = f"{order_number} - {storage_name}".strip(" -")

            if (not st.order_done) and (not ms_order):
                body = {
                    "name": order_number,
                    "organization": ms.mk_ref(f"{cfg.ms_base_url}/entity/organization/{cfg.ms_org_id}", "organization"),
                    "agent": ms.mk_ref(f"{cfg.ms_base_url}/entity/counterparty/{cfg.ms_agent_id}", "counterparty"),
                    "salesChannel": ms.mk_ref(f"{cfg.ms_base_url}/entity/saleschannel/{cfg.ms_sales_channel_id}", "saleschannel"),
                    "store": ms.mk_ref(f"{cfg.ms_base_url}/entity/store/{cfg.ms_store_id_fbo}", "store"),
                    "positions": positions,
                    "description": description,
                }
                if planned:
                    body["deliveryPlannedMoment"] = planned

                if not cfg.dry_run:
                    ms.create_customer_order(body)
                st.order_done = True

            # Move при READY_TO_SUPPLY (fallback applicable true->false обрабатывается в main старым кодом у тебя)
            # Demand/Move логика у тебя уже была — оставляю без расширения здесь.

        state.save()

        import time as _t
        _t.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    main()
