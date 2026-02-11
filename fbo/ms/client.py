from __future__ import annotations

import json
import random
import time
import requests
from typing import Any, Dict, Optional


class MsHttpError(RuntimeError):
    def __init__(self, status_code: int, text: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(f"MS HTTP {status_code}: {text[:1000]}")
        self.status_code = status_code
        self.text = text
        self.payload = payload or {}

    def json(self) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(self.text)
        except Exception:
            return None


class MoySkladClient:
    def __init__(self, base_url: str, token: str, rps: float = 4.0, retry_max: int = 6, retry_base_seconds: float = 0.6):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json;charset=utf-8",
                "Content-Type": "application/json",
            }
        )
        self.rps = max(0.1, float(rps))
        self.retry_max = max(0, int(retry_max))
        self.retry_base = max(0.1, float(retry_base_seconds))
        self._next_allowed_ts = 0.0

    def _throttle(self) -> None:
        now = time.time()
        if now < self._next_allowed_ts:
            time.sleep(self._next_allowed_ts - now)
        # разрешаем следующий запрос через 1/rps
        self._next_allowed_ts = time.time() + (1.0 / self.rps)

    def _request(self, method: str, path: str, *, params=None, payload=None, timeout: int = 60) -> Dict[str, Any]:
        url = self.base_url + path

        last_err: Optional[MsHttpError] = None
        for attempt in range(self.retry_max + 1):
            self._throttle()
            r = self.session.request(method, url, params=params, json=payload, timeout=timeout)

            if 200 <= r.status_code < 300:
                return r.json()

            # retry on 429 / 503 / 504
            if r.status_code in (429, 503, 504) and attempt < self.retry_max:
                base = self.retry_base * (2 ** attempt)
                jitter = random.uniform(0, 0.25 * base)
                time.sleep(base + jitter)
                continue

            last_err = MsHttpError(r.status_code, r.text, payload=payload)
            break

        assert last_err is not None
        raise last_err

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Dict[str, Any]:
        return self._request("GET", path, params=params, timeout=timeout)

    def post(self, path: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        return self._request("POST", path, payload=payload, timeout=timeout)

    def get_by_href(self, href: str, timeout: int = 60) -> Dict[str, Any]:
        if href.startswith(self.base_url):
            path = href[len(self.base_url):]
        else:
            path = href.replace("https://api.moysklad.ru/api/remap/1.2", "")
        return self.get(path, timeout=timeout)
