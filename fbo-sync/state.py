from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any

@dataclass
class SupplyState:
    last_state: str | None = None
    order_done: bool = False
    move_done: bool = False
    demand_done: bool = False

class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            self.data = json.loads(self.path.read_text("utf-8") or "{}")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")

    def get(self, order_number: str) -> SupplyState:
        raw = self.data.get(order_number, {})
        return SupplyState(
            last_state=raw.get("last_state"),
            order_done=bool(raw.get("order_done", False)),
            move_done=bool(raw.get("move_done", False)),
            demand_done=bool(raw.get("demand_done", False)),
        )

    def set(self, order_number: str, st: SupplyState):
        self.data[order_number] = {
            "last_state": st.last_state,
            "order_done": st.order_done,
            "move_done": st.move_done,
            "demand_done": st.demand_done,
        }
