from app.ms_client import MSClient

def expand_offer(ms: MSClient, offer_id: str, qty: int) -> list[dict]:
    """
    Возвращает список позиций для документов МС.
    Если offer_id = bundle.article -> разворачиваем в components.
    Если product.article -> одна позиция.
    Если не найдено -> пусто (позицию пропускаем).
    """
    bundle = ms.find_bundle_by_article(offer_id)
    if bundle:
        comps = ms.get_bundle_components(bundle["id"])
        out = []
        for c in comps:
            # c["assortment"] meta + quantity in bundle
            comp_qty = int(c.get("quantity") or 0)
            if comp_qty <= 0:
                continue
            out.append({
                "assortment": {"meta": c["assortment"]["meta"]},
                "quantity": qty * comp_qty,
                # цена — дефолтная цена продажи компонента (берём по meta -> надо fetch, но MVP пропускаем цену тут)
            })
        return out

    prod = ms.find_product_by_article(offer_id)
    if not prod:
        return []

    return [{
        "assortment": {"meta": prod["meta"]},
        "quantity": qty,
        # цену проставим при сборке документа (ниже)
    }]
