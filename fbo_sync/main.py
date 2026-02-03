import os
import json
import time
from datetime import datetime, timezone, timedelta

from fbo_sync.ms_api import MS, MoySkladError
from fbo_sync.ozon_fbo import OzonFbo


STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")

# Склады
MS_STORE_ID_SKLAD = "7cdb9b20-9910-11ec-0a80-08670002d998"
MS_STORE_ID_FBO = "77b4a517-3b82-11f0-0a80-18cb00037a24"

# Статусы документов
MOVE_STATE_ID = "b0d2c89d-5c7c-11ef-0a80-0cd4001f5885"
DEMAND_STATE_ID = "b543e330-44e4-11f0-0a80-0da5002260ab"

POLL_SECONDS = 80

# Не ранее 02.02.2026 включительно
MIN_SINCE = datetime(2026, 2, 2, 0, 0, 0, tzinfo=timezone.utc)

# Нам достаточно READY_TO_SUPPLY (как ты сказал — DATA_FILLING не нужен)
STATE_READY_TO_SUPPLY_ENUM = 2


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(st: dict):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def must(k: str) -> str:
    v = os.getenv(k, "").strip()
    if not v:
        raise RuntimeError(f"Missing env {k}")
    return v


def ms_href(base: str, entity: str, id_: str) -> str:
    base = base.rstrip("/")
    return f"{base}/entity/{entity}/{id_}"


def parse_timeslot_date(order: dict) -> str | None:
    # Берём orders.timeslot.timeslot.from -> дата (без времени)
    ts = (order.get("timeslot") or {}).get("timeslot") or {}
    frm = ts.get("from")
    if not frm:
        return None
    # "2026-02-09T11:00:00Z" -> "2026-02-09 00:00:00.000"
    dt = datetime.fromisoformat(frm.replace("Z", "+00:00")).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d 00:00:00.000")


def aggregate_offer_qty_from_bundles(oz: OzonFbo, bundle_ids: list[str]) -> dict[str, int]:
    # offer_id -> qty (сумма quantity)
    out: dict[str, int] = {}
    for bid in bundle_ids:
        items = oz.bundle_items(bid)
        for it in items:
            offer_id = str(it.get("offer_id") or "").strip()
            qty = int(it.get("quantity") or 0)
            if offer_id and qty > 0:
                out[offer_id] = out.get(offer_id, 0) + qty
    return out


def expand_to_products(ms: MS, ms_base: str, offer_qty: dict[str, int]) -> dict[str, float]:
    """
    Возвращает: product_href -> qty
    Правила:
      - если assortment = bundle, разворачиваем в компоненты (product/assortment href из components)
      - если offer_id == "00233" и в МС это bundle:
           разворачиваем как обычно
           + добавляем article="00651" qty = (общее_кол-во_компонентов) / 5
    """
    product_qty: dict[str, float] = {}

    def add(href: str, q: float):
        if q <= 0:
            return
        product_qty[href] = product_qty.get(href, 0.0) + q

    for offer_id, qty_offer in offer_qty.items():
        a = ms.get_assortment_by_article(offer_id)
        if not a:
            # не нашли в МС — пропускаем эту позицию
            continue

        atype = ((a.get("meta") or {}).get("type") or "").lower()
        href = (a.get("meta") or {}).get("href")
        if not href:
            continue

        if atype != "bundle":
            # product/variant/etc — кладём как есть
            add(href, float(qty_offer))
            continue

        # bundle -> components
        bundle_id = a.get("id")
        comps = ms.get_bundle_components(bundle_id)

        total_components_qty = 0.0
        for c in comps:
            comp_ass = c.get("assortment") or {}
            comp_href = (comp_ass.get("meta") or {}).get("href")
            comp_q = float(c.get("quantity") or 0.0)
            if comp_href and comp_q > 0:
                q_total = comp_q * float(qty_offer)
                add(comp_href, q_total)
                total_components_qty += q_total

        # спец-исключение
        if offer_id == "00233":
            # добавить 00651: qty = total_components / 5
            extra = total_components_qty / 5.0
            a2 = ms.get_assortment_by_article("00651")
            if a2 and (a2.get("meta") or {}).get("href"):
                add((a2["meta"]["href"]), extra)

    return product_qty


def _ms_type_from_href(href: str) -> str:
    # href вида .../entity/product/<id> или .../entity/bundle/<id>
    try:
        part = href.split("/entity/", 1)[1]
        t = part.split("/", 1)[0]
        return t if t else "product"
    except Exception:
        return "product"


def build_positions(ms_qty_by_href: dict[str, float]) -> list[dict]:
    positions = []
    for href, q in ms_qty_by_href.items():
        if q <= 0:
            continue
        positions.append({
            "assortment": {
                "meta": {
                    "href": href,
                    "type": _ms_type_from_href(href),  # <-- КЛЮЧЕВОЕ
                    "mediaType": "application/json"
                }
            },
            "quantity": q
        })
    return positions

def create_customerorder(ms: MS, ms_base: str, org_id: str, agent_id: str, sales_channel_id: str, name: str,
                         store_id: str, moment: str | None, description: str, positions: list[dict], dry_run: bool):
    body = {
        "name": name,
        "organization": {"meta": {"href": ms_href(ms_base, "organization", org_id), "type": "organization", "mediaType": "application/json"}},
        "agent": {"meta": {"href": ms_href(ms_base, "counterparty", agent_id), "type": "counterparty", "mediaType": "application/json"}},
        "salesChannel": {"meta": {"href": ms_href(ms_base, "saleschannel", sales_channel_id), "type": "saleschannel", "mediaType": "application/json"}},
        "store": {"meta": {"href": ms_href(ms_base, "store", store_id), "type": "store", "mediaType": "application/json"}},
        "description": description,
        "positions": positions,
    }
    if moment:
        body["deliveryPlannedMoment"] = moment  # плановая дата (в МС это deliveryPlannedMoment)

    if dry_run:
        print(f"[DRY_RUN] create customerorder {name} positions={len(positions)}")
        return {"id": "dry"}

    return ms.create_customerorder(body)


def create_move(ms: MS, ms_base: str, org_id: str, name: str, dry_run: bool, applicable: bool):
    body = {
        "name": name,
        "organization": {"meta": {"href": ms_href(ms_base, "organization", org_id), "type": "organization", "mediaType": "application/json"}},
        "sourceStore": {"meta": {"href": ms_href(ms_base, "store", MS_STORE_ID_SKLAD), "type": "store", "mediaType": "application/json"}},
        "targetStore": {"meta": {"href": ms_href(ms_base, "store", MS_STORE_ID_FBO), "type": "store", "mediaType": "application/json"}},
        "applicable": applicable,
        "state": {"meta": {"href": ms_href(ms_base, "customentity", MOVE_STATE_ID), "type": "state", "mediaType": "application/json"}},
    }

    if dry_run:
        print(f"[DRY_RUN] create move {name} applicable={applicable}")
        return {"id": "dry"}

    return ms.create_move(body)


def create_demand(ms: MS, ms_base: str, org_id: str, agent_id: str, name: str, dry_run: bool):
    body = {
        "name": name,
        "organization": {"meta": {"href": ms_href(ms_base, "organization", org_id), "type": "organization", "mediaType": "application/json"}},
        "agent": {"meta": {"href": ms_href(ms_base, "counterparty", agent_id), "type": "counterparty", "mediaType": "application/json"}},
        "store": {"meta": {"href": ms_href(ms_base, "store", MS_STORE_ID_FBO), "type": "store", "mediaType": "application/json"}},
        "state": {"meta": {"href": ms_href(ms_base, "customentity", DEMAND_STATE_ID), "type": "state", "mediaType": "application/json"}},
    }

    if dry_run:
        print(f"[DRY_RUN] create demand {name}")
        return {"id": "dry"}

    return ms.create_demand(body)


def main():
    oz = OzonFbo(must("OZON_CLIENT_ID"), must("OZON_API_KEY"))
    ms = MS(must("MS_BASE_URL"), must("MS_TOKEN"))

    org_id = must("MS_ORG_ID")
    agent_id = must("MS_AGENT_ID")
    sales_channel_id = must("MS_SALES_CHANNEL_ID")
    dry_run = os.getenv("DRY_RUN", "0").strip() == "1"

    st = load_state()

    while True:
        try:
            now = datetime.now(timezone.utc)
            since = max(now - timedelta(days=10), MIN_SINCE)
            since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            to_iso = iso_now()

            order_ids = oz.list_orders(since_iso, to_iso, states=[STATE_READY_TO_SUPPLY_ENUM], limit=50)
            if not order_ids:
                time.sleep(POLL_SECONDS)
                continue

            # грузим пачками по 50 (API get до 50)
            for i in range(0, len(order_ids), 50):
                batch = order_ids[i:i+50]
                orders = oz.get_orders(batch)

                for o in orders:
                    order_number = str(o.get("order_number") or "").strip()
                    if not order_number:
                        continue

                    # ключ в state = order_number (как ты уже используешь)
                    rec = st.get(order_number) or {"order_done": False, "move_done": False, "demand_done": False, "last_state": None}
                    st.setdefault(order_number, rec)

                    last_state = (o.get("state") or "").strip()
                    rec["last_state"] = last_state

                    # Коммент: "<order_number> - <storage_warehouse.name>"
                    wh_name = ""
                    supplies = o.get("supplies") or []
                    if supplies:
                        sw = (supplies[0].get("storage_warehouse") or {})
                        wh_name = sw.get("name") or ""
                    description = f"{order_number} - {wh_name}".strip(" -")

                    moment = parse_timeslot_date(o)

                    # --- 1) customerorder: создаём если нет в МС ---
                    if not rec.get("order_done"):
                        exists = ms.find_by_name("customerorder", order_number)
                        if exists:
                            rec["order_done"] = True
                        else:
                            bundle_ids = [s.get("bundle_id") for s in (o.get("supplies") or []) if s.get("bundle_id")]
                            offer_qty = aggregate_offer_qty_from_bundles(oz, bundle_ids)
                            ms_qty_by_href = expand_to_products(ms, ms.base, offer_qty)
                            positions = build_positions(ms_qty_by_href)

                            # store = FBO, цены дефолтные МС (price не задаём)
                            create_customerorder(ms, ms.base, org_id, agent_id, sales_channel_id, order_number,
                                                 MS_STORE_ID_FBO, moment, description, positions, dry_run)
                            rec["order_done"] = True

                    # --- 2) move: при READY_TO_SUPPLY ---
                    if last_state == "READY_TO_SUPPLY" and not rec.get("move_done"):
                        # если move уже есть — отмечаем done
                        exists_m = ms.find_by_name("move", order_number)
                        if exists_m:
                            rec["move_done"] = True
                        else:
                            # пробуем applicable=true, если ошибка — false, но если ошибка по name — пропуск
                            try:
                                create_move(ms, ms.base, org_id, order_number, dry_run, applicable=True)
                                rec["move_done"] = True
                            except MoySkladError as e:
                                txt = (e.text or "")
                                if "name" in txt or "уже существует" in txt.lower():
                                    # конфликт номера — пропускаем всю поставку
                                    rec["move_done"] = True
                                else:
                                    # fallback applicable=false
                                    try:
                                        create_move(ms, ms.base, org_id, order_number, dry_run, applicable=False)
                                        rec["move_done"] = True
                                    except MoySkladError as e2:
                                        txt2 = (e2.text or "")
                                        if "name" in txt2 or "уже существует" in txt2.lower():
                                            rec["move_done"] = True
                                        else:
                                            # не смогли — оставляем move_done False, попробуем потом
                                            pass

                    # --- 3) demand: когда ушла из READY_TO_SUPPLY в любой другой кроме CANCELLED ---
                    # (тут demand создаётся по твоему ТЗ, но для этого нужно мониторить изменения состояний.
                    #  Сейчас мы держим только READY_TO_SUPPLY в list — поэтому demand создавай отдельным проходом,
                    #  когда расширишь states. Я не ломаю текущий контур.)
                    # rec["demand_done"] оставляем как есть.

                save_state(st)

            time.sleep(POLL_SECONDS)

        except Exception as e:
            # не умираем — логируем и продолжаем
            print(f"[ERR] {type(e).__name__}: {e}")
            try:
                save_state(st)
            except Exception:
                pass
            time.sleep(5)


if __name__ == "__main__":
    main()
