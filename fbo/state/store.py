from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from fbo.state.models import RootState


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> RootState:
        if not self.path.exists():
            return RootState()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return RootState()
        supplies = data.get("supplies") if isinstance(data, dict) else None
        if not isinstance(supplies, dict):
            supplies = {}
        return RootState(supplies=supplies)

    def save(self, state: RootState) -> None:
        tmp = self.path.with_suffix(".tmp")
        payload: Dict[str, Any] = {"supplies": state.supplies}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
