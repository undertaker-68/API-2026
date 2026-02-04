from ms_api import (
    find_assortment_by_article,
    get_bundle_components,
    get_assortment_by_href,
    get_sale_price,
)
from logger import log


def build_positions(items: list[dict]) -> list[dict]:
    positions: list[dict] = []

    for item in items:
        offer_id = str(item["offer_id"])
        qty = float(item["quantity"])

        log.debug(f"Поиск товара offer_id={offer_id}, qty={qty}")
        assortment = find_assortment_by_article(offer_id)

        if not assortment:
            log.warning(f"Товар не найден: article={offer_id} -> SKIP")
            continue

        a_type = assortment["meta"]["type"]

        if a_type == "bundle":
            # assortment["id"] у bundle — это и есть id комплекта в МС
            components = get_bundle_components(assortment["id"])

            for c in components:
                comp_meta = c["assortment"]["meta"]
                comp_qty = float(c["quantity"]) * qty

                comp_full = get_assortment_by_href(comp_meta["href"])
                price = get_sale_price(comp_full)

                positions.append({
                    "assortment": {"meta": comp_meta},
                    "quantity": comp_qty,
                    "price": price,
                })
        else:
            price = get_sale_price(assortment)
            positions.append({
                "assortment": {"meta": assortment["meta"]},
                "quantity": qty,
                "price": price,
            })

    return positions
