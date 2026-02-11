from __future__ import annotations

import time
import requests
from typing import Any, Dict, Optional


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

        # retry на 429/5xx
        backoff = 0.4
        for attempt in range(1, 8):
            r = self.session.post(url, json=payload, timeout=timeout)

            if r.status_code == 429 or 500 <= r.status_code <= 599:
                if attempt == 7:
                    raise requests.HTTPError(
                        f"{r.status_code} {r.reason} for {url}\nResponse: {r.text}",
                        response=r,
                    )
                time.sleep(backoff)
                backoff = min(backoff * 1.8, 6.0)
                continue

            if r.status_code >= 400:
                raise requests.HTTPError(
                    f"{r.status_code} {r.reason} for {url}\nResponse: {r.text}",
                    response=r,
                )
            return r.json()

        # unreachable
        raise RuntimeError("OzonClient.post: retry loop failed unexpectedly")

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Dict[str, Any]:
        url = self.base_url + path
        r = self.session.get(url, params=params, timeout=timeout)
        if r.status_code >= 400:
            raise requests.HTTPError(
                f"{r.status_code} {r.reason} for {url}\nResponse: {r.text}",
                response=r,
            )
        return r.json()
