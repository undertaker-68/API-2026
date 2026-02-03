import time
import requests


class OzonFbo:
    def __init__(self, client_id: str, api_key: str, timeout: int = 30, retries: int = 8):
        self.base = "https://api-seller.ozon.ru"
        self.timeout = timeout
        self.retries = retries
        self.s = requests.Session()
        self.s.headers.update(
            {
                "Client-Id": str(int(client_id)),  # важно: как int
                "Api-Key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def _post(self, path: str, body: dict) -> dict:
        for attempt in range(self.retries):
            r = self.s.post(self.base + path, json=body, timeout=self.timeout)

            if r.status_code == 429:
                ra = r.headers.get("Retry-After")
                if ra and ra.isdigit():
                    time.sleep(int(ra))
                else:
                    time.sleep(min(1.0 * (attempt + 1), 10.0))
                continue

            r.raise_for_status()
            return r.json()

        raise RuntimeError(f"Ozon 429 (retries exceeded) {path}")

    def list_orders(self, since_iso: str, to_iso: str, states: list[int], limit: int = 50) -> list[int]:
        # Пытаемся пагинацию last_id, если её нет — заберём одну страницу
        order_ids: list[int] = []
        last_id = 0
        while True:
            body = {
                "filter": {"since": since_iso, "to": to_iso, "states": states},
                "sort_by": 1,
                "limit": limit,
            }
            # если API поддерживает last_id — используем
            if last_id:
                body["last_id"] = last_id

            out = self._post("/v3/supply-order/list", body)

            ids = out.get("order_ids") or []
            order_ids.extend(ids)

            # варианты полей пагинации
            has_next = out.get("has_next")
            next_last = out.get("last_id")
            if has_next is True and next_last and str(next_last).isdigit():
                nxt = int(next_last)
                if nxt == last_id:
                    break
                last_id = nxt
                continue

            # если пагинации нет — выходим
            break

        return order_ids

    def get_orders(self, order_ids: list[int]) -> list[dict]:
        out = self._post("/v3/supply-order/get", {"order_ids": order_ids})
        return out.get("orders") or []

    def bundle_items(self, bundle_id: str) -> list[dict]:
        # По документации: limit max 100, last_id строка (может быть "")
        items: list[dict] = []
        last_id = ""
        while True:
            body = {"bundle_ids": [bundle_id], "limit": 100}
            if last_id != "":
                body["last_id"] = last_id
            else:
                body["last_id"] = ""

            out = self._post("/v1/supply-order/bundle", body)
            part = out.get("items") or []
            items.extend(part)

            if not out.get("has_next"):
                break
            last_id = out.get("last_id") or ""
            if last_id == "":
                break

        return items
