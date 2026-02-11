from __future__ import annotations

import os
import random
import time
from typing import Any, Dict, Optional

import requests


class OzonClient:
    def __init__(self, base_url: str, client_id: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Client-Id": client_id,
                "Api-Key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

        # throttle/retry settings (env optional)
        self.rps = float(os.getenv("OZON_RPS", "2"))
        self.retry_max = int(os.getenv("OZON_RETRY_MAX", "6"))
        self.retry_base = float(os.getenv("OZON_RETRY_BASE_SECONDS", "0.7"))
        self._next_allowed_ts = 0.0

        if self.rps <= 0:
            self.rps = 2.0
        if self.retry_max < 0:
            self.retry_max = 0
        if self.retry_base <= 0:
            self.retry_base = 0.7

    def _throttle(self) -> None:
        now = time.time()
        if now < self._next_allowed_ts:
            time.sleep(self._next_allowed_ts - now)
        self._next_allowed_ts = time.time() + (1.0 / self.rps)

    def post(self, path: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        url = self.base_url + path

        last_exc: Optional[requests.HTTPError] = None
        for attempt in range(self.retry_max + 1):
            self._throttle()
            r = self.session.post(url, json=payload, timeout=timeout)

            if 200 <= r.status_code < 300:
                return r.json()

            # retry on 429 / temporary errors
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self.retry_max:
                base = self.retry_base * (2 ** attempt)
                jitter = random.uniform(0, 0.25 * base)
                time.sleep(base + jitter)
                continue

            last_exc = requests.HTTPError(
                f"{r.status_code} {r.reason} for {url}\nResponse: {r.text}",
                response=r,
            )
            break

        assert last_exc is not None
        raise last_exc

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Dict[str, Any]:
        url = self.base_url + path

        last_exc: Optional[requests.HTTPError] = None
        for attempt in range(self.retry_max + 1):
            self._throttle()
            r = self.session.get(url, params=params, timeout=timeout)

            if 200 <= r.status_code < 300:
                return r.json()

            if r.status_code in (429, 500, 502, 503, 504) and attempt < self.retry_max:
                base = self.retry_base * (2 ** attempt)
                jitter = random.uniform(0, 0.25 * base)
                time.sleep(base + jitter)
                continue

            last_exc = requests.HTTPError(
                f"{r.status_code} {r.reason} for {url}\nResponse: {r.text}",
                response=r,
            )
            break

        assert last_exc is not None
        raise last_exc
