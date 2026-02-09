from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional

from fbo.ms.client import MoySkladClient


def assortment_find_by_article(ms: MoySkladClient, article: str) -> Optional[Dict[str, Any]]:
    data = ms.get("/entity/assortment", params={"search": article, "limit": 100})
    rows = data.get("rows") or []
    for r in rows:
        if (r.get("article") or "").strip() == article.strip():
            return r
    return rows[0] if rows else None


def get_sale_price_value(assortment_full: Dict[str, Any]) -> int:
    """
    Возвращает цену 'Цена продажи' (value — int, копейки*100).
    Если нет — берём первую.
    """
    sale_prices = assortment_full.get("salePrices") or []
    for p in sale_prices:
        pt = p.get("priceType") or {}
        if (pt.get("name") or "").strip() == "Цена продажи":
            return int(p.get("value") or 0)
    if sale_prices:
        return int(sale_prices[0].get("value") or 0)
    return 0


def bundle_components(ms: MoySkladClient, bundle_href: str) -> List[Tuple[Dict[str, Any], float]]:
    """
    Возвращает список (assortment_short_meta, qty_in_bundle)
    """
    bundle = ms.get_by_href(bundle_href)
    comps = (bundle.get("components") or {}).get("rows") or []
    out: List[Tuple[Dict[str, Any], float]] = []
    for row in comps:
        qty = row.get("quantity")
        assort = row.get("assortment")
        if not assort or qty is None:
            continue
        try:
            q = float(qty)
        except Exception:
            continue
        if q <= 0:
            continue
        out.append((assort, q))
    return out
