import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
import requests


class MoySkladError(RuntimeError):
    def __init__(self, status: int, text: str):
        super().__init__(f"MS error {status}: {text}")
        self.status = status
        self.text = text


@dataclass
class MS:
    base: str
    token: str
    timeout: int = 30
    retries: int = 8

    def __post_init__(self):
        self.s = requests.Session()
        self.s.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                # ВАЖНО: МС требует именно такой Accept
                "Accept": "application/json;charset=utf-8",
                "Content-Type": "application/json",
            }
        )
        self.base = self.base.rstrip("/")

    def _sleep_on_429(self, r: requests.Response, attempt: int):
        # МС отдаёт свои хедеры
        ra = r.headers.get("x-lognex-retry-after")
        ti = r.headers.get("x-lognex-retry-timeinterval")
        wait_ms = None
        if ra and ra.isdigit():
            wait_ms = int(ra)
        elif ti and ti.isdigit():
            wait_ms = int(ti)
        if wait_ms is None:
            wait_ms = min(3000 * (attempt + 1), 15000)
        time.sleep(wait_ms / 1000.0)

    def _get(self, path: str, params: dict | None = None) -> dict:
        last_err = None
        for attempt in range(self.retries):
            r = self.s.get(self.base + path, params=params, timeout=self.timeout)

            if r.status_code == 429:
                self._sleep_on_429(r, attempt)
                continue

            if r.status_code >= 400:
                raise MoySkladError(r.status_code, r.text)

            return r.json()

        # если всё плохо — не делаем вид что rows=[]
        raise MoySkladError(429, "Rate limit (retries exceeded)")

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        last_err = None
        for attempt in range(self.retries):
            r = self.s.post(self.base + path, json=body, timeout=self.timeout)

            if r.status_code == 429:
                self._sleep_on_429(r, attempt)
                continue

            if r.status_code >= 400:
                raise MoySkladError(r.status_code, r.text)

            return r.json()

        raise MoySkladError(429, "Rate limit (retries exceeded)")

    def find_by_name(self, entity: str, name: str) -> Optional[dict]:
        out = self._get(f"/entity/{entity}", params={"filter": f"name={name}"})
        rows = out.get("rows") or []
        return rows[0] if rows else None

    def get_assortment_by_article(self, article: str) -> Optional[dict]:
        # Ищем по ассортименту — там может быть product / bundle
        out = self._get("/entity/assortment", params={"filter": f"article={article}"})
        rows = out.get("rows") or []
        return rows[0] if rows else None

    def get_bundle_components(self, bundle_id: str) -> list[dict]:
        # Компоненты комплекта
        out = self._get(f"/entity/bundle/{bundle_id}/components")
        return out.get("rows") or []

    def create_customerorder(self, body: dict) -> dict:
        return self._post("/entity/customerorder", body)

    def create_move(self, body: dict) -> dict:
        return self._post("/entity/move", body)

    def create_demand(self, body: dict) -> dict:
        return self._post("/entity/demand", body)
