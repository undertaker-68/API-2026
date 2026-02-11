from __future__ import annotations


def error_text(e: Exception) -> str:
    return str(e)


def is_duplicate_number(e: Exception) -> bool:
    s = str(e).lower()
    return (
        "документ с таким номером уже существует" in s
        or "same name already exists" in s
        or "already exists" in s
    )
