from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, Optional

import requests


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
    def __init__(
        self,
        base_url: str,
        token: str,
        rps: float = 3.0,
        retry_max: int = 6,
        retry_base_seconds: float = 0.6,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json;charset=utf-8",
                "Content-Type": "application/json",
            }
        )
        self._min_interval = 1.0 / max(0.1, float(rps))
        self._last_ts = 0.0
        self._retry_max = int(retry_max)
        self._retry_base = float(retry_base_seconds)

    def _throttle(self) -> None:
        now = time.time()
        delta = now - self._last_ts
        if delta < self._min_interval:
            time.sleep(self._min_interval - delta)
        self._last_ts = time.time()

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        if path_or_url.startswith("http"):
            full = path_or_url
        else:
            full = self.base_url + path_or_url

        last_err: Exception | None = None
        for attempt in range(1, self._retry_max + 1):
            self._throttle()
            try:
                if method == "GET":
                    r = self.session.get(full, params=params, timeout=timeout)
                else:
                    r = self.session.post(full, json=payload, timeout=timeout)

                if r.status_code in (429,) or 500 <= r.status_code < 600:
                    sleep_s = min(12.0, self._retry_base * (2 ** (attempt - 1)) + random.random() * 0.25)
                    time.sleep(sleep_s)
                    continue

                if r.status_code >= 400:
                    raise MsHttpError(r.status_code, r.text, payload)

                return r.json()
            except Exception as e:
                last_err = e
                time.sleep(min(5.0, 0.2 * attempt))
                continue

        if last_err:
            raise last_err
        raise RuntimeError("MS request failed")

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Dict[str, Any]:
        return self._request("GET", path, params=params, timeout=timeout)

    def post(self, path: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        return self._request("POST", path, payload=payload, timeout=timeout)

    def get_by_href(self, href: str, timeout: int = 60) -> Dict[str, Any]:
        return self._request("GET", href, timeout=timeout)
