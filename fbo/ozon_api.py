import requests
from datetime import date, timedelta, datetime, time, timezone

from config import OZON_BASE_URL, OZON_HEADERS, MIN_CREATED_DATE, DAYS_BACK


STATE_CODE = {
    "READY_TO_SUPPLY": 2,
    "ACCEPTED_AT_SUPPLY_WAREHOUSE": 3,
    "IN_TRANSIT": 4,
    "ACCEPTANCE_AT_STORAGE_WAREHOUSE": 5,
    "COMPLETED": 8,
    "REJECTED_AT_SUPPLY_WAREHOUSE": 9,
    "CANCELLED": 10,
    "OVERDUE": 11,
}

# какие статусы нам нужны
LIST_STATES_READY = [STATE_CODE["READY_TO_SUPPLY"]]
LIST_STATES_AFTER_READY = [
    STATE_CODE["ACCEPTED_AT_SUPPLY_WAREHOUSE"],
    STATE_CODE["IN_TRANSIT"],
    STATE_CODE["ACCEPTANCE_AT_STORAGE_WAREHOUSE"],
    STATE_CODE["COMPLETED"],
    STATE_CODE["REJECTED_AT_SUPPLY_WAREHOUSE"],
    STATE_CODE["OVERDUE"],
]
LIST_STATES_CANCELLED = [STATE_CODE["CANCELLED"]]


def _dt_utc_z(d: date, end: bool = False) -> str:
    dt = datetime.combine(d, time(23, 59, 59) if end else time(0, 0, 0), tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _list_by_states(states: list[int]) -> list[int]:
    url = f"{OZON_BASE_URL}/v3/supply-order/list"

    since_date = max(date.today() - timedelta(days=DAYS_BACK), MIN_CREATED_DATE)
    to_date = date.today()

    payload = {
        "filter": {
            "since": _dt_utc_z(since_date, end=False),
            "to": _dt_utc_z(to_date, end=True),
            "states": states,     # ОБЯЗАТЕЛЬНО и только числа
        },
        "limit": 100,
        "last_id": "",
        "offset": 0,
        "sort_by": 1,            # валидно, проверили
        "sort_dir": 2,           # DESC, иначе ругается на архив
    }

    ids: list[int] = []

    while True:
        r = requests.post(url, json=payload, headers=OZON_HEADERS)
        if r.status_code >= 400:
            raise RuntimeError(f"Ozon {r.status_code}: {r.text} | payload={payload}")

        data = r.json()
        ids.extend(data.get("order_ids", []) or [])

        last_id = data.get("last_id") or ""
        if not last.id:
            break

        payload["last_id"] = last_id

    return ids


def get_supply_orders_ids():
    """
    Возвращаем order_id всех поставок по нужным статусам (ready + after_ready + cancelled)
    за последние DAYS_BACK дней, но не ранее MIN_CREATED_DATE.
    """
    ids = []
    ids.extend(_list_by_states(LIST_STATES_READY))
    ids.extend(_list_by_states(LIST_STATES_AFTER_READY))
    ids.extend(_list_by_states(LIST_STATES_CANCELLED))
    # убираем дубли, сохраняем порядок
    seen = set()
    out = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def get_supply_orders_info(order_ids: list[int]):
    url = f"{OZON_BASE_URL}/v3/supply-order/get"
    r = requests.post(url, headers=OZON_HEADERS, json={"order_ids": order_ids})
    r.raise_for_status()
    return r.json()["orders"]


def get_bundle_items(bundle_ids):
    url = f"{OZON_BASE_URL}/v1/supply-order/bundle"
    r = requests.post(
        url,
        headers=OZON_HEADERS,
        json={"bundle_ids": bundle_ids, "limit": 100},
    )
    r.raise_for_status()
    return r.json()["items"]
