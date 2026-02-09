from __future__ import annotations

import requests
from typing import Any, Dict, Optional


class MoySkladClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json;charset=utf-8",
                "Content-Type": "application/json",
            }
        )

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Dict[str, Any]:
        r = self.session.get(self.base_url + path, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        r = self.session.post(self.base_url + path, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def get_by_href(self, href: str, timeout: int = 60) -> Dict[str, Any]:
        """
        href обычно полный: https://api.moysklad.ru/api/remap/1.2/entity/...
        Превращаем в path относительно base_url.
        """
        if href.startswith(self.base_url):
            path = href[len(self.base_url) :]
        else:
            # fallback
            path = href.replace("https://api.moysklad.ru/api/remap/1.2", "")
        return self.get(path, timeout=timeout)
