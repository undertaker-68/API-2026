import time
import requests
from config import MS_HEADERS, MS_BASE_URL

# простой in-memory cache на время запуска
_CACHE: dict[str, dict] = {}


def _get(url: str, *, max_retries: int = 8, timeout: int = 30) -> dict:
    # cache
    if url in _CACHE:
        return _CACHE[url]

    delay = 0.5
    last_err = None

    for attempt in range(1, max_retries + 1):
        r = requests.get(url, headers=MS_HEADERS, timeout=timeout)

        if r.status_code == 200:
            data = r.json()
            _CACHE[url] = data
            return data

        # 429 / временные ошибки -> backoff
        if r.status_code in (429, 503, 504):
            last_err = (r.status_code, r.text)
            time.sleep(delay)
            delay = min(delay * 2, 8.0)
            continue

        # прочие ошибки — сразу
        r.raise_for_status()

    raise RuntimeError(f"MS GET failed after retries: url={url} last={last_err}")


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
