import time
import requests
from typing import Any

from config import MS_HEADERS, MS_BASE_URL

# in-memory cache на время запуска
_CACHE: dict[str, Any] = {}


def _request(method: str, url: str, *, json: dict | None = None,
             max_retries: int = 8, timeout: int = 30) -> requests.Response:
    delay = 0.5
    last_err = None

    for _ in range(max_retries):
        r = requests.request(method, url, headers=MS_HEADERS, json=json, timeout=timeout)

        if r.status_code < 400:
            return r

        # 429 / временные ошибки -> backoff
        if r.status_code in (429, 503, 504):
            last_err = (r.status_code, r.text)
            time.sleep(delay)
            delay = min(delay * 2, 8.0)
            continue

        # прочие — сразу, но с телом ошибки
        raise RuntimeError(f"MS {method} {url} failed: {r.status_code} {r.text}")


    raise RuntimeError(f"MS {method} failed after retries: url={url} last={last_err}")


def _get(url: str) -> dict:
    if url in _CACHE:
        return _CACHE[url]
    r = _request("GET", url)
    data = r.json()
    _CACHE[url] = data
    return data


def find_customerorder_by_name(name: str) -> dict | None:
    url = f"{MS_BASE_URL}/entity/customerorder?filter=name={name}"
    data = _get(url)
    rows = data.get("rows") or []
    return rows[0] if rows else None


def create_customerorder(payload: dict) -> dict:
    url = f"{MS_BASE_URL}/entity/customerorder"
    r = _request("POST", url, json=payload)
    return r.json()


def find_assortment_by_article(article: str) -> dict | None:
    url = f"{MS_BASE_URL}/entity/assortment?filter=article={article}"
    data = _get(url)
    rows = data.get("rows") or []
    return rows[0] if rows else None


def get_bundle_components(bundle_id: str) -> list[dict]:
    url = f"{MS_BASE_URL}/entity/bundle/{bundle_id}/components"
    data = _get(url)
    return data.get("rows") or []


def get_assortment_by_href(href: str) -> dict:
    return _get(href)


def get_sale_price(assortment: dict) -> int:
    """
    Возвращает цену в копейках (как в МС).
    Берём первую цену из salePrices, иначе 0.
    """
    sale_prices = assortment.get("salePrices") or []
    if sale_prices:
        v = sale_prices[0].get("value")
        if isinstance(v, (int, float)):
            return int(v)
    return 0
