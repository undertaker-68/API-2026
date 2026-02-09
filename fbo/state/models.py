from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class SupplyState:
    supply_order_id: int | None = None
    last_status: str = "UNKNOWN"
    warehouse: str = ""
    ms_exists: bool = False
    ms_created: bool = False
    ms_customerorder_href: str = ""
    updated_at: str = ""
    skip_reason: str = ""


@dataclass
class RootState:
    supplies: Dict[str, Dict[str, Any]] = field(default_factory=dict)
