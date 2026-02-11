from __future__ import annotations

import random
import time
from typing import Any, Dict

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

    def post(self, path: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        url = self.base_url + path

        last_exc: Exception | None = None
        for attempt in range(1, 8):
            try:
                r = self.session.post(url, json=payload, timeout=timeout)
                if r.status_code == 429 or 500 <= r.status_code < 600:
                    sleep_s = min(8.0, (0.5 * (2 ** (attempt - 1))) + random.random() * 0.3)
                    time.sleep(sleep_s)
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last_exc = e
                time.sleep(min(3.0, 0.2 * attempt))
                continue

        if last_exc:
            raise last_exc
        raise RuntimeError(f"Ozon request failed: {path}")
