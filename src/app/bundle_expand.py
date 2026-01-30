from __future__ import annotations

from app.ms_client import MSClient


# Минимальная нормализация “похожих” кириллических букв в латиницу.
# Этого хватает для кейсов типа 10264-А93 -> 10264-A93
_CYR_TO_LAT = str.maketrans({
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M",
    "О": "O", "Р": "P", "Т": "T", "Х": "X", "У": "Y",
    "а": "a", "в": "b", "с": "c", "е": "e", "н": "h", "к": "k", "м": "m",
    "о": "o", "р": "p", "т": "t", "х": "x", "у": "y",
    "–": "-", "—": "-", "−": "-",
})


def normalize_offer_id(s: str) -> str:
    return str(s or "").strip().translate(_CYR_TO_LAT)


def _pos(meta: dict, qty: int, price: int | None) -> dict:
    p = {
        "assortment": {"meta": meta},
        "quantity": qty,
    }
    # В МС price опционален, но ты хочешь дефолтную цену продажи.
    if price is not None:
        p["price"] = int(price)
    return p


def expand_offer(ms: MSClient, offer_id: str, qty: int) -> list[dict]:
    """
    Возвращает список позиций для документов МС.
    Правило:
    1) exact bundle by article (offer_id)
    2) exact product by article
    3) exact variant by article
    4) fallback: assortment search + exact article
    Если bundle найден — разворачиваем в components.
    """
    raw = str(offer_id or "").strip()
    if not raw or qty <= 0:
        return []

    candidates = [raw]
    norm = normalize_offer_id(raw)
    if norm and norm != raw:
        candidates.append(norm)

    # --- 1) bundle exact
    for key in candidates:
        bundle = ms.find_bundle_by_article_exact(key)
        if bundle:
            comps = ms.get_bundle_components(bundle["id"])
            out: list[dict] = []
            for c in comps:
                comp_qty = int(c.get("quantity") or 0)
                if comp_qty <= 0:
                    continue

                assort = c.get("assortment") or {}
                meta = (assort.get("meta") or {})
                if not meta:
                    continue

                # цена компонента: если assortment уже expanded, попробуем взять salePrices прямо отсюда
                price = ms.get_sale_price_value(assort)
                if price is None and meta.get("href"):
                    # fallback: fetch entity by meta.href
                    ent = ms.get_by_meta_href(meta["href"])
                    price = ms.get_sale_price_value(ent)

                out.append(_pos(meta, qty * comp_qty, price))
            return out

    # --- 2) product exact
    for key in candidates:
        prod = ms.find_product_by_article_exact(key)
        if prod:
            meta = (prod.get("meta") or {})
            price = ms.get_sale_price_value(prod)
            return [_pos(meta, qty, price)]

    # --- 3) variant exact
    for key in candidates:
        var = ms.find_variant_by_article_exact(key)
        if var:
            meta = (var.get("meta") or {})
            price = ms.get_sale_price_value(var)
            return [_pos(meta, qty, price)]

    # --- 4) fallback assortment search exact article
    for key in candidates:
        row = ms.find_assortment_by_article_search_exact(key)
        if not row:
            continue
        meta = (row.get("meta") or {})
        t = meta.get("type")
        if t == "bundle":
            # повторим нормальный bundle путь, но уже по id
            comps = ms.get_bundle_components(row["id"])
            out: list[dict] = []
            for c in comps:
                comp_qty = int(c.get("quantity") or 0)
                if comp_qty <= 0:
                    continue
                assort = c.get("assortment") or {}
                m = (assort.get("meta") or {})
                if not m:
                    continue
                price = ms.get_sale_price_value(assort)
                if price is None and m.get("href"):
                    ent = ms.get_by_meta_href(m["href"])
                    price = ms.get_sale_price_value(ent)
                out.append(_pos(m, qty * comp_qty, price))
            return out
        if t in ("product", "variant"):
            price = ms.get_sale_price_value(row)
            if price is None and meta.get("href"):
                ent = ms.get_by_meta_href(meta["href"])
                price = ms.get_sale_price_value(ent)
            return [_pos(meta, qty, price)]

    return []
