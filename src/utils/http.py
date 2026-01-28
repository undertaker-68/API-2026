import time
import requests

def post_json(url: str, headers: dict, payload: dict, timeout: int = 30, retries: int = 3) -> dict:
    last_err = None
    for i in range(retries):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (i + 1))
    raise last_err  # type: ignore

def get_json(url: str, headers: dict, timeout: int = 30, retries: int = 3) -> dict:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (i + 1))
    raise last_err  # type: ignore
