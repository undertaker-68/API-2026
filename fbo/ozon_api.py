import requests
from datetime import datetime, timedelta, date
from config import OZON_BASE_URL, OZON_HEADERS, MIN_CREATED_DATE, DAYS_BACK


def get_supplies():
    url = f"{OZON_BASE_URL}/v3/supply-order/list"
    result = []

    since = max(
        date.today() - timedelta(days=DAYS_BACK),
        MIN_CREATED_DATE
    )

    payload = {
        "filter": {
            "since": since.isoformat(),
            "states": []
        },
        "limit": 1000,
        "offset": 0
    }

    while True:
        r = requests.post(url, json=payload, headers=OZON_HEADERS)
        r.raise_for_status()
        data = r.json()

        for order in data.get("orders", []):
            if not order["order_tags"].get("is_super_fbo"):
                continue

            created = datetime.fromisoformat(
                order["created_date"].replace("Z", "")
            ).date()

            if created < MIN_CREATED_DATE:
                continue

            result.append(order)

        if not data.get("has_next"):
            break

        payload["offset"] += payload["limit"]

    return result


def get_bundle_items(bundle_ids):
    url = f"{OZON_BASE_URL}/v1/supply-order/bundle"
    r = requests.post(
        url,
        headers=OZON_HEADERS,
        json={"bundle_ids": bundle_ids, "limit": 100},
    )
    r.raise_for_status()
    return r.json()["items"]
