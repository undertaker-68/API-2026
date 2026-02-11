from __future__ import annotations

from typing import Any, Dict, List, Tuple

from fbo.ms.article_cache import ArticleCache


def ms_meta(entity: str, id_: str) -> Dict[str, Any]:
    """
    Важно: base_url у нас в проекте всегда https://api.moysklad.ru/api/remap/1.2
    поэтому href собираем статически (как и было в рабочей версии).
    """
    return {
        "meta": {
            "href": f"https://api.moysklad.ru/api/remap/1.2/entity/{entity}/{id_}",
            "type": entity,
            "mediaType": "application/json",
        }
    }


def build_positions_from_items(
    cache: ArticleCache,
    items: List[Tuple[str, float]],  # (offer_id/article, qty)
) -> tuple[List[Dict[str, Any]], List[str]]:
    """
    items: список (article, qty) где article == offer_id из Ozon и == article в МС
    Комплекты разворачиваем в компоненты.
    Цена = стандартная цена товара (Sale price) берется из ArticleCache.resolve()
    """
    positions: List[Dict[str, Any]] = []
    missing: List[str] = []

    for article, qty in items:
        a = (article or "").strip()
        if not a:
            continue

        resolved = cache.resolve(a)

        if resolved.kind == "missing" or not resolved.meta:
            missing.append(a)
            continue

        if resolved.kind == "bundle":
            # qty комплекта * qty компонента
            for c in resolved.components:
                q = qty * c.qty
                positions.append(
                    {
                        "quantity": q,
                        "price": c.price,
                        "assortment": {"meta": c.meta},
                        "reserve": q,
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
    """
    Собираем payload для CustomerOrder.
    store обязателен (ты это увидел по ошибкам).
    planned_moment пишем в deliveryPlannedMoment если он есть.
    """
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

    # пустой заказ допустим (как ты говорил), но если позиции есть — кладем
    if positions:
        payload["positions"] = positions

    return payload
