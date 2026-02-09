from __future__ import annotations

from typing import Any, Dict, List, Tuple

from fbo.ms.client import MoySkladClient
from fbo.ms.assortment import (
    assortment_find_by_article,
    bundle_components,
    get_sale_price_value,
)


def ms_meta(entity: str, id_: str) -> Dict[str, Any]:
    return {
        "meta": {
            "href": f"https://api.moysklad.ru/api/remap/1.2/entity/{entity}/{id_}",
            "type": entity,
            "mediaType": "application/json",
        }
    }


def build_customerorder_payload(
    ms: MoySkladClient,
    supply_number: str,
    warehouse_name: str,
    items: List[Tuple[str, float]],  # (offer_id/article, qty)
    org_id: str,
    agent_id: str,
    sales_channel_id: str,
    state_id: str,
) -> Dict[str, Any]:
    """
    - name = supply_number
    - description = "<номер поставки> - <склад назначения>"
    - prices = MS sale price "Цена продажи"
    - bundles expanded into components
    """
    description = f"{supply_number} - {warehouse_name}"

    positions: List[Dict[str, Any]] = []

    for article, qty in items:
        assort_short = assortment_find_by_article(ms, article)
        if not assort_short:
            continue

        assort_href = (assort_short.get("meta") or {}).get("href")
        if not assort_href:
            continue

        assort_full = ms.get_by_href(assort_href)
        a_meta = assort_full.get("meta") or {}
        a_type = a_meta.get("type") or (assort_short.get("meta") or {}).get("type")

        if a_type == "bundle":
            comps = bundle_components(ms, assort_href)
            for comp_assort_short, comp_qty in comps:
                comp_href = (comp_assort_short.get("meta") or {}).get("href")
                if not comp_href:
                    continue
                comp_full = ms.get_by_href(comp_href)
                price = get_sale_price_value(comp_full)
                positions.append(
                    {
                        "quantity": qty * comp_qty,
                        "price": price,
                        "assortment": {"meta": (comp_full.get("meta") or {})},
                        "reserve": qty * comp_qty,
                    }
                )
        else:
            price = get_sale_price_value(assort_full)
            positions.append(
                {
                    "quantity": qty,
                    "price": price,
                    "assortment": {"meta": a_meta},
                    "reserve": qty,
                }
            )

    payload: Dict[str, Any] = {
        "name": supply_number,
        "description": description,
        "organization": ms_meta("organization", org_id),
        "agent": ms_meta("counterparty", agent_id),
        "salesChannel": ms_meta("saleschannel", sales_channel_id),
        "state": ms_meta("state", state_id),
        "positions": positions,
    }
    return payload
