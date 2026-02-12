from __future__ import annotations

from typing import Any, Dict, Optional

from fbo.ms.client import MoySkladClient
from fbo.ms.errors import is_duplicate_number
from fbo.ms.find_by_name import find_by_name


def _ms_meta(entity: str, id_: str) -> Dict[str, Any]:
    return {
        "meta": {
            "href": f"https://api.moysklad.ru/api/remap/1.2/entity/{entity}/{id_}",
            "type": entity,
            "mediaType": "application/json",
        }
    }


def _customerorder_meta(href: str) -> Dict[str, Any]:
    return {"meta": {"href": href, "type": "customerorder", "mediaType": "application/json"}}


def find_move(ms: MoySkladClient, name: str) -> Optional[Dict[str, Any]]:
    return find_by_name(ms, "move", name)


def create_move_with_applicable(
    ms: MoySkladClient,
    *,
    name: str,
    description: str,
    org_id: str,
    agent_id: str,
    state_id: str,
    source_store_id: str,
    target_store_id: str,
    positions: list[dict],
    customerorder_href: str | None,
    dry_run: bool,
) -> tuple[bool, Dict[str, Any] | None, str]:
    """
    returns (created_or_exists, created_doc_or_none, reason)
    reason:
      ok | dry_run | duplicate_number | error_applicable_failed
    """
    existing = find_move(ms, name)
    if existing:
        return True, existing, "ok"

    payload_base: Dict[str, Any] = {
        "name": name,
        "description": description,
        "organization": _ms_meta("organization", org_id),
        "agent": _ms_meta("counterparty", agent_id),
        "state": _ms_meta("state", state_id),
        "sourceStore": _ms_meta("store", source_store_id),
        "targetStore": _ms_meta("store", target_store_id),
        "positions": positions,
    }

    if customerorder_href:
        payload_base["customerOrder"] = _customerorder_meta(customerorder_href)

    if dry_run:
        return True, None, "dry_run"

    # applicable=True then False
    for applicable in (True, False):
        payload = dict(payload_base)
        payload["applicable"] = applicable
        try:
            created = ms.post("/entity/move", payload)
            return True, created, "ok"
        except Exception as e:
            if is_duplicate_number(e):
                return False, None, "duplicate_number"
            # else retry with applicable=False

    return False, None, "error_applicable_failed"
