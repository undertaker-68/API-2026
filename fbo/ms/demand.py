from __future__ import annotations

from typing import Any, Dict

from fbo.ms.client import MoySkladClient
from fbo.ms.errors import is_duplicate_number
from fbo.ms.find_by_name import find_by_name


def _ms_meta(entity: str, id_: str) -> Dict[str, Any]:
    return {"meta": {"href": f"https://api.moysklad.ru/api/remap/1.2/entity/{entity}/{id_}", "type": entity, "mediaType": "application/json"}}


def find_demand(ms: MoySkladClient, name: str):
    return find_by_name(ms, "demand", name)


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
    dry_run: bool,
) -> tuple[bool, Dict[str, Any] | None, str]:
    """
    returns (created_or_exists, created_doc_or_none, reason)
    reason: ok | dry_run | duplicate_number | error_applicable_failed | error_other
    """
    existing = find_demand(ms, name)
    if existing:
        return True, existing, "ok"

    payload_base = {
        "name": name,
        "description": description,
        "organization": _ms_meta("organization", org_id),
        "agent": _ms_meta("counterparty", agent_id),
        "state": _ms_meta("state", state_id),
        "store": _ms_meta("store", store_id),
        "positions": positions,
    }

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
