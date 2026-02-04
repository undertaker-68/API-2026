import requests
from config import MS_BASE_URL, MS_HEADERS


def find_assortment_by_article(article):
    url = f"{MS_BASE_URL}/entity/assortment"
    r = requests.get(
        url,
        headers=MS_HEADERS,
        params={"filter": f"article={article}"}
    )
    r.raise_for_status()
    rows = r.json().get("rows", [])
    return rows[0] if rows else None


def get_assortment_by_href(href):
    r = requests.get(href, headers=MS_HEADERS)
    r.raise_for_status()
    return r.json()


def get_bundle_components(bundle_id):
    url = f"{MS_BASE_URL}/entity/bundle/{bundle_id}/components"
    r = requests.get(url, headers=MS_HEADERS)
    r.raise_for_status()
    return r.json()["rows"]


def find_customerorder_by_name(name):
    url = f"{MS_BASE_URL}/entity/customerorder"
    r = requests.get(
        url,
        headers=MS_HEADERS,
        params={"filter": f"name={name}"}
    )
    r.raise_for_status()
    rows = r.json().get("rows", [])
    return rows[0] if rows else None


def create_customerorder(payload):
    url = f"{MS_BASE_URL}/entity/customerorder"
    r = requests.post(url, headers=MS_HEADERS, json=payload)
    r.raise_for_status()
    return r.json()


def get_sale_price(assortment):
    for p in assortment.get("salePrices", []):
        if p["priceType"]["name"] == "Цена продажи":
            return p["value"]
    return 0
