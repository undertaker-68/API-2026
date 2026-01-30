import logging
from typing import Optional

import requests

from app.config import Config

log = logging.getLogger("ms")


class MSClient:
    """
    Минимальный клиент МойСклад REMAP 1.2
    ВАЖНО:
      - Accept должен быть строго application/json;charset=utf-8 (иначе 1062)
      - filter на строки с дефисами часто валится 400 -> используем search + exact match
    """

    def __init__(self, cfg_or_token: Config | str, base: str | None = None):
        # Поддержка двух режимов:
        # 1) MSClient(cfg)  <- как у тебя в main.py
        # 2) MSClient(token, base=...)
        if hasattr(cfg_or_token, "ms_token"):
            cfg: Config = cfg_or_token  # type: ignore[assignment]
            token = cfg.ms_token
            base_url = cfg.ms_base_url
        else:
            token = str(cfg_or_token)
            base_url = base or "https://api.moysklad.ru/api/remap/1.2"

        self.base = (base_url or "https://api.moysklad.ru/api/remap/1.2").rstrip("/")
        self.token = (token or "").strip()

        if not self.token:
            raise ValueError("MS_TOKEN is empty")

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json;charset=utf-8",
            "Content-Type": "application/json",
        }

    # -----------------------------
    # Low-level http
    # -----------------------------
    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
    ) -> dict:
        url = f"{self.base}{path}"
        try:
            r = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                json=body,
                timeout=30,
            )
        except Exception as e:
            log.error("MS %s %s network error: %s", method, path, e)
            raise

        if r.status_code >= 400:
            log.error(
                "MS %s %s failed: %s %s | params=%s | body_keys=%s",
                method,
                path,
                r.status_code,
                r.text,
                params,
                list(body.keys()) if isinstance(body, dict) else None,
            )
            raise requests.HTTPError(f"{r.status_code} {r.text}", response=r)

        if not r.text:
            return {}
        return r.json()

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, body=body)

    def _put(self, path: str, body: dict) -> dict:
        return self._request("PUT", path, body=body)

    # -----------------------------
    # Helpers
    # -----------------------------
    @staticmethod
    def _swap_lookalike_letters(s: str) -> str:
        """
        Подмена визуально похожих кириллица<->латиница.
        Нужно для кейса 10264-А93 (кирилл А) vs 10264-A93 (лат A).
        """
        c2l = {
            "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
            "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
        }
        l2c = {v: k for k, v in c2l.items()}

        out = []
        for ch in s:
            if ch in c2l:
                out.append(c2l[ch])
            elif ch in l2c:
                out.append(l2c[ch])
            else:
                out.append(ch)
        return "".join(out)

    def _article_candidates(self, article: str) -> list[str]:
        article = (article or "").strip()
        if not article:
            return []
        variants = {article}
        variants.add(self._swap_lookalike_letters(article))
        variants.add(article.replace("—", "-").replace("–", "-"))
        variants.add(self._swap_lookalike_letters(article.replace("—", "-").replace("–", "-")))
        return [v for v in variants if v]

    # -----------------------------
    # CustomerOrder
    # -----------------------------
    def find_customer_order_by_name(self, name: str) -> Optional[dict]:
        target = str(name).strip()
        if not target:
            return None

        res = self._get("/entity/customerorder", params={"search": target, "limit": 100, "offset": 0})
        rows = res.get("rows") or []
        for r in rows:
            if (r.get("name") or "").strip() == target:
                return r
        return None

    def get_customer_order(self, order_id: str) -> dict:
        return self._get(f"/entity/customerorder/{order_id}")

    def create_customer_order(self, body: dict) -> dict:
        return self._post("/entity/customerorder", body)

    def update_customer_order(self, order_id: str, body: dict) -> dict:
        return self._put(f"/entity/customerorder/{order_id}", body)

    def set_order_state(self, order_id: str, state_id: str) -> dict:
        return self.update_customer_order(order_id, {
            "state": {"meta": {"href": f"{self.base}/entity/customerorder/metadata/states/{state_id}", "type": "state"}}
        })

    def set_order_reserve(self, order_id: str, reserve: bool) -> dict:
        return self.update_customer_order(order_id, {"reserve": bool(reserve)})

    # -----------------------------
    # Demand / Move
    # -----------------------------
    def create_demand(self, body: dict) -> dict:
        return self._post("/entity/demand", body)

    def create_move(self, body: dict) -> dict:
        return self._post("/entity/move", body)

    # -----------------------------
    # Assortment / Bundle lookup by article
    # -----------------------------
    def find_assortment_by_article_search_exact(self, article: str) -> Optional[dict]:
        for cand in self._article_candidates(article):
            offset = 0
            limit = 100

            while True:
                res = self._get("/entity/assortment", params={"search": cand, "limit": limit, "offset": offset})
                rows = res.get("rows") or []

                # exact-match: только полное совпадение article
                for r in rows:
                    if (r.get("article") or "").strip() == cand:
                        return r

                # пагинация: если строк меньше limit — это последняя страница
                if len(rows) < limit:
                    break

                offset += limit

        return None

    def get_bundle(self, bundle_id: str) -> dict:
        return self._get(f"/entity/bundle/{bundle_id}", params={"expand": "components.assortment"})

    def try_get_bundle_by_article(self, article: str) -> Optional[dict]:
        a = self.find_assortment_by_article_search_exact(article)
        if not a:
            return None
        meta = (a.get("meta") or {})
        if meta.get("type") != "bundle":
            return None
        href = meta.get("href") or ""
        bundle_id = href.rstrip("/").split("/")[-1]
        if not bundle_id:
            return None
        return self.get_bundle(bundle_id)

    # -----------------------------
    # Prices
    # -----------------------------
    @staticmethod
    def get_sale_price(entity: dict) -> Optional[int]:
        sale_prices = entity.get("salePrices") or []
        for p in sale_prices:
            price_type = (p.get("priceType") or {}).get("name") or ""
            if price_type.strip().lower() in ("цена продажи", "sale price", "sell price", "розничная"):
                value = p.get("value") or 0
                try:
                    return int(value)
                except Exception:
                    return None
        return None
