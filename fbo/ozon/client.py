from __future__ import annotations

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
            }
        )

    def post(self, path: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        url = self.base_url + path
        r = self.session.post(url, json=payload, timeout=timeout)
        if r.status_code >= 400:
            # ВАЖНО: покажем тело, чтобы понять: версия метода или invalid key (у Ozon это тоже 404)
            raise requests.HTTPError(
                f"{r.status_code} {r.reason} for {url}\nResponse: {r.text}",
                response=r,
            )
        return r.json()

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Dict[str, Any]:
        url = self.base_url + path
        r = self.session.get(url, params=params, timeout=timeout)
        if r.status_code >= 400:
            raise requests.HTTPError(
                f"{r.status_code} {r.reason} for {url}\nResponse: {r.text}",
                response=r,
            )
        return r.json()
