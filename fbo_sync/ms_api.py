from __future__ import annotations

import time
import requests
from typing import Dict, Any, List, Tuple, Optional


class MoySkladError(Exception):
    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        super().__init__(f"MS error {status}: {payload}")


def _is_name_conflict(payload: Any) -> bool:
    txt = str(payload).lower()
    return ("name" in txt) or ("номер" in txt)


class MoySkladClient:
    """
    Важное:
    - НЕ ставим Content-Type в session headers (иначе можно получить 415 на GET).
    - Делаем мягкий rate-limit (МС показывает x-ratelimit-limit=45 и retry-timeinterval=3000ms).
    - На 429: ждём столько, сколько рекомендует МС (x-lognex-retry-after/x-lognex-retry-timeinterval),
      иначе экспоненциальный backoff.
    - Кешируем:
      * assortment по article
      * components по bundle_id
      * find_by_name на короткое время (чтобы не долбить по 3 запроса на каждую поставку каждый цикл)
    """

    def __init__(self, base_url: str, token: str, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json;charset=utf-8",
        })

        # --- rate limit ---
        # МС обычно лимитирует "45 запросов / 3 сек" => ~15 rps. Делаем ~10-12 rps безопасно.
        self._min_interval_sec = 0.09
        self._last_req_ts = 0.0

        # --- caches ---
        self._assortment_by_article: Dict[str, Dict[str, Any]] = {}
        self._bundle_components_by_id: Dict[str, List[Tuple[Dict[str, Any], float]]] = {}

        # короткий кеш на find_by_name (на 10 сек)
        self._find_cache: Dict[Tuple[str, str], Tuple[float, Optional[Dict[str, Any]]]] = {}
        self._find_cache_ttl = 10.0

    def _throttle(self):
        now = time.time()
        dt = now - self._last_req_ts
        if dt < self._min_interval_sec:
            time.sleep(self._min_interval_sec - dt)
        self._last_req_ts = time.time()

    @staticmethod
    def _retry_sleep_from_headers(r: requests.Response) -> Optional[float]:
        """
        МС часто отдаёт:
          x-lognex-retry-after: 0
          x-lognex-retry-timeinterval: 3000   (мс)
        либо Retry-After (сек)
        """
        ra = r.headers.get("Retry-After")
        if ra:
            try:
                return float(ra)
            except Exception:
                pass

        x_after = r.headers.get("x-lognex-retry-after")
        if x_after:
            try:
                ms = float(x_after)
                if ms > 0:
                    return ms / 1000.0
            except Exception:
                pass

        x_interval = r.headers.get("x-lognex-retry-timeinterval")
        if x_interval:
            try:
                ms = float(x_interval)
                if ms > 0:
                    return ms / 1000.0
            except Exception:
                pass

        return None

    def _get(self, path: str, params: dict | None = None) -> dict:
        backoff = 0.5
        for _ in range(10):
            self._throttle()
            r = self.s.get(self.base + path, params=params, timeout=self.timeout)

            if r.status_code != 429:
                if r.status_code >= 400:
                    raise MoySkladError(r.status_code, r.text)
                return r.json()

            # 429
            sleep_s = self._retry_sleep_from_headers(r)
            if sleep_s is None:
                sleep_s = backoff
                backoff = min(backoff * 2.0, 8.0)
            time.sleep(sleep_s)

        # после ретраев
        raise MoySkladError(429, "Too Many Requests (retries exceeded)")

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        backoff = 0.5
        for _ in range(10):
            self._throttle()
            r = self.s.post(
                self.base + path,
                json=body,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},  # только на POST
            )

            if r.status_code != 429:
                if r.status_code >= 400:
                    raise MoySkladError(r.status_code, r.text)
                return r.json()

            sleep_s = self._retry_sleep_from_headers(r)
            if sleep_s is None:
                sleep_s = backoff
                backoff = min(backoff * 2.0, 8.0)
            time.sleep(sleep_s)

        raise MoySkladError(429, "Too Many Requests (retries exceeded)")

    def mk_ref(self, entity: str, id_: str) -> Dict[str, Any]:
        return {
            "meta": {
                "href": f"{self.base}/entity/{entity}/{id_}",
                "type": entity,
                "mediaType": "application/json",
            }
        }

    def find_by_name(self, entity: str, name: str) -> Dict[str, Any] | None:
        key = (entity, name)
        now = time.time()
        cached = self._find_cache.get(key)
        if cached and (now - cached[0] < self._find_cache_ttl):
            return cached[1]

        out = self._get(f"/entity/{entity}", params={"filter": f"name={name}"})
        rows = out.get("rows", []) or []
        res = rows[0] if rows else None
        self._find_cache[key] = (now, res)
        return res

    def get_assortment_by_article(self, article: str) -> Dict[str, Any] | None:
        if article in self._assortment_by_article:
            return self._assortment_by_article[article]

        out = self._get("/entity/assortment", params={"filter": f"article={article}"})
        rows = out.get("rows", []) or []
        res = rows[0] if rows else None
        if res:
            self._assortment_by_article[article] = res
        return res

    def get_bundle_components(self, bundle_id: str) -> List[Tuple[Dict[str, Any], float]]:
        if bundle_id in self._bundle_components_by_id:
            return self._bundle_components_by_id[bundle_id]

        bundle = self._get(f"/entity/bundle/{bundle_id}")
        comps = (bundle.get("components") or {}).get("rows", []) or []
        res: List[Tuple[Dict[str, Any], float]] = []
        for c in comps:
            res.append((c["assortment"]["meta"], float(c["quantity"])))

        self._bundle_components_by_id[bundle_id] = res
        return res

    # ----------------------------
    # Создание документов
    # ----------------------------
    def create_customerorder(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/customerorder", body)

    def create_move(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/move", body)

    def create_demand(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/entity/demand", body)
