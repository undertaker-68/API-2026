import os
import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any

BASE = "https://api-seller.ozon.ru"

def ozon_headers() -> dict:
    cid = os.getenv("OZON_CLIENT_ID") or os.getenv("OZON_CLIENTID") or os.getenv("CLIENT_ID")
    key = os.getenv("OZON_API_KEY") or os.getenv("OZON_APIKEY") or os.getenv("API_KEY")
    if not cid or not key:
        raise RuntimeError("Нет OZON_CLIENT_ID / OZON_API_KEY в env (.env не подхватился?)")
    return {
        "Client-Id": str(cid),
        "Api-Key": str(key),
        "Content-Type": "application/json",
    }

def post(path: str, payload: dict) -> dict:
    r = requests.post(BASE + path, headers=ozon_headers(), json=payload, timeout=60)
    r.raise_for_status()
    return r.json()

def iso_to_dt(s: str) -> datetime:
    # Ozon обычно отдаёт ISO с Z или +00:00
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)

def list_ids(limit_pages: int = 200) -> List[int]:
    ids = []
    last_id = 0
    for _ in range(limit_pages):
        data = post("/v3/supply-order/list", {"limit": 100, "last_id": last_id})
        items = data.get("result", [])
        if not items:
            break
        for it in items:
            if "order_id" in it:
                ids.append(int(it["order_id"]))
        last_id = int(items[-1].get("order_id", 0))
        if last_id == 0:
            break
        time.sleep(0.05)
    return ids

def get_info(ids: List[int]) -> List[Dict[str, Any]]:
    out = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i+50]
        data = post("/v3/supply-order/get", {"order_ids": chunk})
        out.extend(data.get("result", []))
        time.sleep(0.05)
    return out

def main():
    # твои требования:
    min_date = datetime(2026, 2, 2, 0, 0, 0, tzinfo=timezone.utc)  # "не ранее 02.02.2026 включительно"
    ten_days_ago = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=10)
    cutoff = max(min_date, ten_days_ago)

    print("Cutoff UTC:", cutoff.isoformat())

    ids = list_ids()
    print("Total ids from list:", len(ids))

    sample = ids[:200]  # достаточно, чтобы увидеть диапазон дат
    infos = get_info(sample)

    rows = []
    for o in infos:
        oid = o.get("id") or o.get("order_id")
        created = o.get("created_at")
        state = o.get("state")
        if created:
            dt = iso_to_dt(created)
            rows.append((oid, dt, created, state))
        else:
            rows.append((oid, None, None, state))

    rows.sort(key=lambda x: (x[1] is None, x[1] or datetime(1970,1,1,tzinfo=timezone.utc)))

    print("\nSAMPLE (sorted by created_at):")
    for oid, dt, created, state in rows[:20]:
        print(f"{oid} | {created} | {state}")
    print("...")
    for oid, dt, created, state in rows[-20:]:
        print(f"{oid} | {created} | {state}")

    # Теперь уже честная оценка “сколько проходит по cutoff” на всей выборке
    infos_all = get_info(ids[:500])  # сначала 500 для скорости, потом можно увеличить
    ok = 0
    for o in infos_all:
        created = o.get("created_at")
        if not created:
            continue
        if iso_to_dt(created) >= cutoff:
            ok += 1
    print(f"\nIn first 500 supplies, >= cutoff: {ok}")

if __name__ == "__main__":
    main()
