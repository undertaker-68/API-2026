from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from fbo.ms.client import MoySkladClient
from fbo.ms.assortment import assortment_find_by_article, bundle_components, get_sale_price_value


@dataclass
class Component:
    meta: Dict[str, Any]
    qty: float
    price: int


@dataclass
class Resolved:
    kind: str  # 'product' | 'bundle' | 'missing'
    meta: Optional[Dict[str, Any]]
    price: int
    components: List[Component]


class ArticleCache:
    def __init__(self, ms: MoySkladClient, path: str):
        self.ms = ms
        self.path = path
        self._cache: Dict[str, Dict[str, Any]] = {}

    def load(self) -> None:
        p = Path(self.path)
        if not p.exists():
            self._cache = {}
            return
        try:
            self._cache = json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            self._cache = {}

    def save(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.path).write_text(json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def resolve(self, article: str) -> Resolved:
        a = article.strip()
        if not a:
            return Resolved("missing", None, 0, [])

        if a in self._cache:
            c = self._cache[a]
            kind = c.get("kind", "missing")
            meta = c.get("meta")
            price = int(c.get("price") or 0)
            comps = []
            for row in c.get("components") or []:
                comps.append(Component(meta=row["meta"], qty=float(row["qty"]), price=int(row.get("price") or 0)))
            return Resolved(kind, meta, price, comps)

        short = assortment_find_by_article(self.ms, a)
        if not short:
            self._cache[a] = {"kind": "missing"}
            return Resolved("missing", None, 0, [])

        meta = (short.get("meta") or {})
        href = meta.get("href")
        type_ = meta.get("type")

        full = self.ms.get_by_href(href) if href else short
        price = get_sale_price_value(full)

        if type_ == "bundle":
            comps_raw = bundle_components(self.ms, href)
            comps: List[Component] = []
            for comp_meta, qty in comps_raw:
                comp_href = (comp_meta.get("meta") or {}).get("href")
                comp_full = self.ms.get_by_href(comp_href) if comp_href else {}
                comp_price = get_sale_price_value(comp_full) if comp_full else 0
                comps.append(Component(meta=comp_meta.get("meta") or comp_meta, qty=float(qty), price=int(comp_price)))
            self._cache[a] = {
                "kind": "bundle",
                "meta": meta,
                "price": int(price),
                "components": [{"meta": c.meta, "qty": c.qty, "price": c.price} for c in comps],
            }
            return Resolved("bundle", meta, int(price), comps)

        self._cache[a] = {"kind": "product", "meta": meta, "price": int(price), "components": []}
        return Resolved("product", meta, int(price), [])
