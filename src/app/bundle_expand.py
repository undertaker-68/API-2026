import logging

from app.ms_client import MSClient

log = logging.getLogger("bundle")


def expand_offer(ms: MSClient, offer_id: str, qty: int) -> list[dict]:
    """
    Возвращает позиции МС для заказа:
      - если offer_id -> product: одна позиция
      - если offer_id -> bundle: разворачиваем в components (qty * component.quantity)
    Формат позиции (минимально нужный для CustomerOrder.positions):
      {"assortment": {"meta": {...}}, "quantity": N}
    """
    offer_id = (offer_id or "").strip()
    if not offer_id or qty <= 0:
        return []

    # 1) Пытаемся найти напрямую в ассортименте по article
    a = ms.find_assortment_by_article_search_exact(offer_id)
    if not a:
        # 2) Отдельно попытка bundle по article (на практике часто достаточно п.1)
        b = ms.try_get_bundle_by_article(offer_id)
        if not b:
            return []
        return _expand_bundle(b, qty)

    meta = (a.get("meta") or {})
    t = meta.get("type")
    if t == "bundle":
        href = meta.get("href") or ""
        bundle_id = href.rstrip("/").split("/")[-1]
        if not bundle_id:
            return []
        b = ms.get_bundle(bundle_id)
        return _expand_bundle(b, qty)

    # product / variant / service — в заказ можно класть как есть
    return [{
        "assortment": {"meta": meta},
        "quantity": int(qty),
    }]


def _expand_bundle(bundle: dict, qty: int) -> list[dict]:
    comps = bundle.get("components") or {}
    rows = comps.get("rows") or []
    out: list[dict] = []
    for c in rows:
        comp_qty = c.get("quantity")
        try:
            comp_qty = int(comp_qty)
        except Exception:
            continue
        ass = (c.get("assortment") or {})
        meta = (ass.get("meta") or {})
        if not meta:
            continue
        out.append({
            "assortment": {"meta": meta},
            "quantity": int(qty) * int(comp_qty),
        })
    return out
