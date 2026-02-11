from __future__ import annotations

from typing import Any, Dict, Optional
from fbo.ms.client import MoySkladClient


def find_by_name(ms: MoySkladClient, entity: str, name: str) -> Optional[Dict[str, Any]]:
    data = ms.get(f"/entity/{entity}", params={"filter": f"name={name}"})
    rows = data.get("rows") or []
    return rows[0] if rows else None
