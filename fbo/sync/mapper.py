from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional

from fbo.ms.client import MoySkladClient
from fbo.ms.assortment import (
    assortment_find_by_article,
    bundle_components,
    get_sale_price_value,
)


def ms_meta(ms: MoySkladClient, entity: str, id_: str) -> Dict[str, Any]:
    return {
        "meta": {
            "href": f"{ms.base_url}/entity/{entity}/{id_}",
            "type": entity,
            "mediaType": "application/json",
        }
    }


def build_ms_positions(
    ms: MoySkladClient,
    items: List[Tuple[str, float]],  # (article, qty)
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    - price = sale price ("Цена продажи")
    - bundles expanded into components
    - ВАЖНО: НЕ пишем reserve в позициях (оно ломало создание)
    """
    positions: List[Dict[str, Any]] = []
    missing: List[str] = []

    for article, qty in items:
        assort_short = assortment_find_by_article(ms, article)
        if not assort_short:
            missing.append(article)
            continue

        assort_href = (assort_short.get("meta") or {}).get("href")
        if not assort_href:
            missing.append(article)
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
                    }
                )
        else:
            price = get_sale_price_value(assort_full)
            positions.append(
                {
                    "quantity": qty,
                    "price": price,
                    "assortment": {"meta": a_meta},
                }
            )

    return positions, missing


def build_customerorder_payload(
    ms: MoySkladClient,
    supply_number: str,
    dest_warehouse_name: str,
    planned_to_iso_z: Optional[str],
    items: List[Tuple[str, float]],
    org_id: str,
    agent_id: str,
    sales_channel_id: str,
    state_id: str,
    dest_store_id: str,
) -> Tuple[Dict[str, Any], List[str]]:
    description = f"{supply_number} - {dest_warehouse_name}"

    positions, missing = build_ms_positions(ms, items)

    payload: Dict[str, Any] = {
        "name": supply_number,
        "description": description,
        "organization": ms_meta(ms, "organization", org_id),
        "agent": ms_meta(ms, "counterparty", agent_id),
        "salesChannel": ms_meta(ms, "saleschannel", sales_channel_id),
        "state": ms_meta(ms, "state", state_id),
        "store": ms_meta(ms, "store", dest_store_id),
        "positions": positions,
        # резерв на уровне документа (если надо — включено; МС это умеет)
        "reserve": True,
    }

    if planned_to_iso_z:
        # поле "План. дата отгрузки" у CustomerOrder
        payload["deliveryPlannedMoment"] = planned_to_iso_z

    return payload, missing
