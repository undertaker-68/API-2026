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
        r.raise_for_status()
        return r.json()

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Dict[str, Any]:
        url = self.base_url + path
        r = self.session.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
