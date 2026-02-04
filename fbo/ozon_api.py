import requests
from datetime import datetime, timedelta, date

from config import OZON_BASE_URL, OZON_HEADERS, MIN_CREATED_DATE, DAYS_BACK


def _dt_z(d: date, end: bool = False) -> str:
    # Ozon любит RFC3339 с Z
    return f"{d.isoformat()}T23:59:59Z" if end else f"{d.isoformat()}T00:00:00Z"


def get_supplies():
    url = f"{OZON_BASE_URL}/v3/supply-order/list"
    result = []

    today = date.today()
    since_date = max(today - timedelta(days=DAYS_BACK), MIN_CREATED_DATE)
    to_date = today

    payload = {
        "filter": {
            "since": _dt_z(since_date, end=False),
            "to": _dt_z(to_date, end=True),
             "sort_by": "SORT_BY_CREATED_AT",
             "sort_dir": "SORT_DIR_ASC",
        },
        "limit": 100,
        "offset": 0,
    }

    while True:
        r = requests.post(url, json=payload, headers=OZON_HEADERS)

        if r.status_code >= 400:
            # чтобы сразу видеть причину 400
            raise RuntimeError(f"Ozon {r.status_code}: {r.text}")

        data = r.json()

        orders = data.get("orders", [])
        result.extend(orders)

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
