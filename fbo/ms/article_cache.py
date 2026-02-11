from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fbo.ms.client import MoySkladClient
from fbo.ms.assortment import assortment_find_by_article, get_sale_price_value, bundle_components


@dataclass
class Component:
    meta: Dict[str, Any]
    qty: float
    price: int


@dataclass
class ArticleResolved:
    kind: str  # product|bundle|missing
    meta: Optional[Dict[str, Any]] = None
    price: int = 0
    components: List[Component] = None  # for bundles


class ArticleCache:
    def __init__(self, ms: MoySkladClient, path: str):
        self.ms = ms
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            self._cache = {}
            return
        try:
            self._cache = json.loads(self.path.read_text(encoding="utf-8")) or {}
        except Exception:
            self._cache = {}

    def save(self) -> None:
        self.path.write_text(json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def resolve(self, article: str) -> ArticleResolved:
        self.load()
        a = article.strip()
        if a in self._cache:
            return self._from_dict(self._cache[a])

        # find assortment by article
        short = assortment_find_by_article(self.ms, a)
        if not short or not (short.get("meta") or {}).get("href"):
            d = {"kind": "missing"}
            self._cache[a] = d
            return self._from_dict(d)

        full = self.ms.get_by_href(short["meta"]["href"])
        meta = full.get("meta") or {}
        kind = meta.get("type") or "unknown"

        if kind == "bundle":
            comps = []
            for comp_short, comp_qty in bundle_components(self.ms, short["meta"]["href"]):
                href = (comp_short.get("meta") or {}).get("href")
                if not href:
                    continue
                comp_full = self.ms.get_by_href(href)
                price = get_sale_price_value(comp_full)
                comps.append({"meta": comp_full.get("meta") or {}, "qty": float(comp_qty), "price": int(price)})
            d = {"kind": "bundle", "meta": meta, "components": comps}
            self._cache[a] = d
            return self._from_dict(d)

        # product/service/variant/etc
        price = get_sale_price_value(full)
        d = {"kind": "product", "meta": meta, "price": int(price)}
        self._cache[a] = d
        return self._from_dict(d)

    @staticmethod
    def _from_dict(d: Dict[str, Any]) -> ArticleResolved:
        kind = d.get("kind", "missing")
        if kind == "bundle":
            comps = [Component(meta=c["meta"], qty=float(c["qty"]), price=int(c["price"])) for c in (d.get("components") or [])]
            return ArticleResolved(kind="bundle", meta=d.get("meta"), components=comps)
        if kind == "product":
            return ArticleResolved(kind="product", meta=d.get("meta"), price=int(d.get("price") or 0), components=[])
        return ArticleResolved(kind="missing", meta=None, price=0, components=[])
