from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from fbo.ms.client import MoySkladClient
from fbo.ms.errors import is_duplicate_number
from fbo.ms.find_by_name import find_by_name


def _ms_meta(ms: MoySkladClient, entity: str, id_: str) -> Dict[str, Any]:
    return {
        "meta": {
            "href": f"{ms.base_url}/entity/{entity}/{id_}",
            "type": entity,
            "mediaType": "application/json",
        }
    }


def _ms_meta_href(href: str, type_: str) -> Dict[str, Any]:
    return {"meta": {"href": href, "type": type_, "mediaType": "application/json"}}


def create_demand_with_applicable(
    ms: MoySkladClient,
    *,
    name: str,
    description: str,
    org_id: str,
    agent_id: str,
    state_id: str,
    store_id: str,
    positions: list[dict],
    customerorder_href: Optional[str] = None,
    dry_run: bool,
) -> Tuple[bool, Dict[str, Any] | None, str]:
    existing = find_by_name(ms, "demand", name)
    if existing:
        return True, existing, "ok"

    payload_base: Dict[str, Any] = {
        "name": name,
        "description": description,
        "organization": _ms_meta(ms, "organization", org_id),
        "agent": _ms_meta(ms, "counterparty", agent_id),
        "state": _ms_meta(ms, "state", state_id),
        "store": _ms_meta(ms, "store", store_id),
        "positions": positions,
    }
    if customerorder_href:
        payload_base["customerOrder"] = _ms_meta_href(customerorder_href, "customerorder")

    if dry_run:
        return True, None, "dry_run"

    for applicable in (True, False):
        payload = dict(payload_base)
        payload["applicable"] = applicable
        try:
            created = ms.post("/entity/demand", payload)
            return True, created, "ok"
        except Exception as e:
            if is_duplicate_number(e):
                return False, None, "duplicate_number"

    return False, None, "error_applicable_failed"
