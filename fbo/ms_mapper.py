from ms_api import (
    find_assortment_by_article,
    get_bundle_components,
    get_assortment_by_href,
    get_sale_price
)
from logger import log


def build_positions(items):
    positions = []

    for item in items:
        offer_id = item["offer_id"]
        qty = item["quantity"]

        log.debug(f"Поиск товара offer_id={offer_id}, qty={qty}")
        assortment = find_assortment_by_article(offer_id)

        if not assortment:
            log.error(f"Товар не найден: article={offer_id}")
            continue

        a_type = assortment["meta"]["type"]

        if a_type == "bundle":
            components = get_bundle_components(assortment["id"])

            for c in components:
                comp_meta = c["assortment"]["meta"]
                comp_qty = c["quantity"] * qty

                comp_full = get_assortment_by_href(comp_meta["href"])
                price = get_sale_price(comp_full)

                log.debug(
                    f"Компонент {comp_full.get('article')} "
                    f"qty={comp_qty} price={price}"
                )

                positions.append({
                    "assortment": comp_meta,
                    "quantity": comp_qty,
                    "price": price
                })
        else:
            price = get_sale_price(assortment)
            log.debug(f"Товар {offer_id} price={price}")

            positions.append({
                "assortment": assortment["meta"],
                "quantity": qty,
                "price": price
            })

    return positions
