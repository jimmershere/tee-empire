"""Cross-brand revenue / performance analytics."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from .store import Store


def empire_overview(store: Optional[Store] = None) -> Dict[str, Any]:
    store = store or Store()
    stats = store.brand_stats()
    total = {
        "brands": len(stats),
        "concepts": sum(s["concepts"] for s in stats),
        "designs": sum(s["designs"] for s in stats),
        "listings": sum(s["listings"] for s in stats),
        "live_listings": sum(s["live"] for s in stats),
        "net_revenue_cents": sum(s["net_cents"] for s in stats),
    }
    return {"total": total, "by_brand": stats}


def top_sellers(store: Optional[Store] = None, brand: Optional[str] = None,
                limit: int = 10) -> List[Dict[str, Any]]:
    store = store or Store()
    sales = store.list_sales(brand=brand)
    tally: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"qty": 0, "net_cents": 0, "platform": "", "brand": ""}
    )
    for s in sales:
        key = f"{s.platform}:{s.listing_external_id}"
        tally[key]["qty"] += s.qty
        tally[key]["net_cents"] += s.net_cents
        tally[key]["platform"] = s.platform
        tally[key]["brand"] = s.brand
        tally[key]["external_id"] = s.listing_external_id
    ranked = sorted(tally.values(), key=lambda r: r["net_cents"], reverse=True)
    return ranked[:limit]


def funnel_by_brand(store: Optional[Store] = None) -> List[Dict[str, Any]]:
    """Concepts -> Designs -> Listings -> Live -> Sales conversion view."""
    store = store or Store()
    stats = store.brand_stats()
    out = []
    for s in stats:
        c = s["concepts"] or 0
        d = s["designs"] or 0
        ll = s["listings"] or 0
        live = s["live"] or 0
        out.append({
            "brand": s["brand"],
            "concepts": c,
            "designed_pct": _pct(d, c),
            "listed_pct": _pct(ll, c),
            "live_pct": _pct(live, c),
            "net_revenue_cents": s["net_cents"],
        })
    return out


def _pct(num: int, denom: int) -> float:
    if not denom:
        return 0.0
    return round(num * 100.0 / denom, 1)
