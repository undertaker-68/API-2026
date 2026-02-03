from __future__ import annotations

import time
import requests
from typing import Dict, Any, Optional


class MoySkladError(Exception):
    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        super().__init__(f"MS error {status}: {payload}")


def _is_name_conflict(payload: Any) -> bool:
    txt = str(payload).lower()
    return ("name" in txt) or ("номер" in txt)


class MS:
    """
    Основной клиент МойСклад для FBO-синхронизации.
    Важно:
    - Accept должен быть строго application/json;charset=utf-8 (у тебя это уже подтверждено)
    - На GET НЕ ставим Content-Type, чтобы не ловить 415
    - На 429 делаем retry
    """

    def __init__(self, base_url: str, token: str, timeout: int = 30, retries: int = 5):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries

        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json;charset=utf-8",
        })

    def _sleep_on_429(self, r: requests.Response, attempt: int):
        # fallback: экспонента + подсказки MS
        retry_after = r.headers.get("x-lognex-retry-after")
        try:
            sec = float(retry_after) if retry_after else 0.0
        except Exception:
            sec = 0.0
        base = max(sec, 1.0)
        time.sleep(min(base * (2 ** attempt), 8.0))

    def _get(self, path: str, params: dict | None = None) -> Dict[str, Any]:
        last_err = None
        for attempt in range(self.retries):
            r = self.s.get(self.base + path, params=params, timeout=self.timeout)

            if r.status_code == 429:
                last_err = r.text
                self._sleep_on_429(r, attempt)
                continue

            if r.status_code >= 400:
                raise MoySkladError(r.status_code, r.text)

            return r.json()

        # если всё плохо — не делаем вид что rows=[]
        raise MoySkladError(429, last_err or "Rate limit (retries exceeded)")

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        last_err = None
        for attempt in range(self.retries):
            r = self.s.post(self.base + path, json=body, timeout=self.timeout)

            if r.status_code == 429:
                last_err = r.text
                self._sleep_on_429(r, attempt)
                continue

            if r.status_code >= 400:
                raise MoySkladError(r.status_code, r.text)

            return r.json()

        raise MoySkladError(429, last_err or "Rate limit (retries exceeded)")

    def find_by_name(self, entity: str, name: str) -> Optional[dict]:
        out = self._get(f"/entity/{entity}", params={"filter": f"name={name}"})
        rows = out.get("rows") or []
        return rows[0] if rows else None

    def get_assortment_by_article(self, article: str) -> Optional[dict]:
        # Важно: ищем в assortment, т.к. это может быть и product и bundle
        out = self._get("/entity/assortment", params={"filter": f"article={article}"})
        rows = out.get("rows") or []
        return rows[0] if rows else None

    def get_bundle_components(self, bundle_id: str) -> list[dict]:
        # КЛЮЧЕВОЕ: компоненты берутся через /components
        out = self._get(f"/entity/bundle/{bundle_id}/components")
        return out.get("rows") or []

    def create_customerorder(self, body: dict) -> dict:
        return self._post("/entity/customerorder", body)

    def create_move(self, body: dict) -> dict:
        return self._post("/entity/move", body)

    def create_demand(self, body: dict) -> dict:
        return self._post("/entity/demand", body)

    def try_create_move_with_fallback(self, body: Dict[str, Any]) -> Dict[str, Any] | None:
        # 1) пробуем applicable=true
        b1 = dict(body)
        b1["applicable"] = True
        try:
            return self.create_move(b1)
        except MoySkladError as e:
            if _is_name_conflict(e.payload):
                return None
            # 2) пробуем applicable=false
            b2 = dict(body)
            b2["applicable"] = False
            try:
                return self.create_move(b2)
            except MoySkladError as e2:
                if _is_name_conflict(e2.payload):
                    return None
                raise


# Алиасы, чтобы не ломались ручные тесты и старые импорты:
MoySkladClient = MS
MoySklad = MS
