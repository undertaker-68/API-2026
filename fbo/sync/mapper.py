from __future__ import annotations

from typing import Any, Dict, List, Tuple
from fbo.ms.article_cache import ArticleCache


def ms_meta(entity: str, id_: str) -> Dict[str, Any]:
    return {
        "meta": {
            "href": f"https://api.moysklad.ru/api/remap/1.2/entity/{entity}/{id_}",
            "type": entity,
            "mediaType": "application/json",
        }
    }


def build_positions_from_items(
    cache: ArticleCache,
    items: List[Tuple[str, float]],
) -> tuple[List[Dict[str, Any]], List[str]]:

    positions: List[Dict[str, Any]] = []
    missing: List[str] = []

    for article, qty in items:
        resolved = cache.resolve(article.strip())

        if resolved.kind == "missing" or not resolved.meta:
            missing.append(article)
            continue

        if resolved.kind == "bundle":
            for c in resolved.components:
                positions.append(
                    {
                        "quantity": qty * c.qty,
                        "price": c.price,
                        "assortment": {"meta": c.meta},
                        "reserve": qty * c.qty,
                    }
                )
        else:
            positions.append(
                {
                    "quantity": qty,
                    "price": resolved.price,
                    "assortment": {"meta": resolved.meta},
                    "reserve": qty,
                }
            )

    return positions, missing


def build_customerorder_payload(
    *,
    supply_number: str,
    comment: str,
    positions: List[Dict[str, Any]],
    org_id: str,
    agent_id: str,
    sales_channel_id: str,
    state_id: str,
    store_id: str,
    planned_moment: str | None,
) -> Dict[str, Any]:

    payload: Dict[str, Any] = {
        "name": supply_number,
        "description": comment,
        "organization": ms_meta("organization", org_id),
        "agent": ms_meta("counterparty", agent_id),
        "salesChannel": ms_meta("saleschannel", sales_channel_id),
        "state": ms_meta("state", state_id),
        "store": ms_meta("store", store_id),
    }

    if planned_moment:
        payload["deliveryPlannedMoment"] = planned_moment

    if positions:
        payload["positions"] = positions

    return payload
