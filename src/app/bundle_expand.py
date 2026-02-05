import logging

from src.app.ms_client import MSClient

log = logging.getLogger("bundle")


def expand_offer(ms: MSClient, offer_id: str, qty: int) -> list[dict]:
    """
    Возвращает позиции МС для заказа:
      - если offer_id -> product/variant/service: одна позиция
      - если offer_id -> bundle: разворачиваем в components (qty * component.quantity)
    ВАЖНО:
      - price = Цена продажи МС (если есть)
    """
    offer_id = (offer_id or "").strip()
    if not offer_id or qty <= 0:
        return []

    # 1) Ищем ассортимент по article
    a = ms.find_assortment_by_article_search_exact(offer_id)
    if not a:
        # 2) Попытка bundle
        b = ms.try_get_bundle_by_article(offer_id)
        if not b:
            return []
        return _expand_bundle(ms, b, qty)

    meta = (a.get("meta") or {})
    price = ms.get_sale_price(a)

    # bundle
    if meta.get("type") == "bundle":
        href = meta.get("href") or ""
        bundle_id = href.rstrip("/").split("/")[-1]
        if not bundle_id:
            return []
        b = ms.get_bundle(bundle_id)
        return _expand_bundle(ms, b, qty)

    # обычный товар / модификация / услуга
    pos = {
        "assortment": {"meta": meta},
        "quantity": int(qty),
    }
    if price is not None:
        pos["price"] = price

    return [pos]


def _expand_bundle(ms: MSClient, bundle: dict, qty: int) -> list[dict]:
    comps = bundle.get("components") or {}
    rows = comps.get("rows") or []
    out: list[dict] = []

    for c in rows:
        try:
            comp_qty = int(c.get("quantity"))
        except Exception:
            continue

        ass = (c.get("assortment") or {})
        meta = (ass.get("meta") or {})
        if not meta:
            continue

        price = ms.get_sale_price(ass)

        pos = {
            "assortment": {"meta": meta},
            "quantity": int(qty) * comp_qty,
        }
        if price is not None:
            pos["price"] = price

        out.append(pos)

    return out
