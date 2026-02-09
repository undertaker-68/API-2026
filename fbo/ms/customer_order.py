from __future__ import annotations

from typing import Any, Dict, Optional

from fbo.ms.client import MoySkladClient


def customerorder_find_by_name(ms: MoySkladClient, name: str) -> Optional[Dict[str, Any]]:
    data = ms.get("/entity/customerorder", params={"filter": f"name={name}"})
    rows = data.get("rows") or []
    return rows[0] if rows else None


def customerorder_create(ms: MoySkladClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return ms.post("/entity/customerorder", payload)
