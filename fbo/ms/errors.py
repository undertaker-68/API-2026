from __future__ import annotations

from typing import Any, Dict, Optional

from fbo.ms.client import MsHttpError


def _flatten_messages(err_json: Dict[str, Any]) -> str:
    parts = []
    if isinstance(err_json.get("message"), str):
        parts.append(err_json["message"])
    errors = err_json.get("errors")
    if isinstance(errors, list):
        for e in errors:
            if isinstance(e, dict) and isinstance(e.get("error"), str):
                parts.append(e["error"])
    return " | ".join(parts)


def is_duplicate_number(e: Exception) -> bool:
    if not isinstance(e, MsHttpError):
        return False
    j = e.json()
    if not isinstance(j, dict):
        return False
    msg = _flatten_messages(j).lower()
    return "документ с таким номером уже существует" in msg or "уже существует" in msg and "номер" in msg


def error_text(e: Exception) -> str:
    if isinstance(e, MsHttpError):
        j = e.json()
        if isinstance(j, dict):
            return _flatten_messages(j)
        return e.text
    return str(e)
