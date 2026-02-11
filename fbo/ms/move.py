from __future__ import annotations

from typing import Any, Dict, Optional
import requests

from fbo.ms.client import MoySkladClient


DUPLICATE_MSG = "Документ с таким номером уже существует"


def move_find_by_name(ms: MoySkladClient, name: str) -> Optional[Dict[str, Any]]:
    data = ms.get("/entity/move", params={"filter": f"name={name}"})
    rows = data.get("rows") or []
    return rows[0] if rows else None


def move_create_with_applicable_fallback(ms: MoySkladClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    applicable=True по умолчанию.
    Если МС ругнулся при сохранении/проведении — пробуем applicable=False.
    """
    try:
        return ms.post("/entity/move", payload)
    except requests.HTTPError as e:
        text = ""
        try:
            text = e.response.text or ""
        except Exception:
            pass

        # дубль номера — наружу, runner решит "финал"
        if DUPLICATE_MSG in text:
            raise

        # fallback applicable=false
        payload2 = dict(payload)
        payload2["applicable"] = False
        return ms.post("/entity/move", payload2)
