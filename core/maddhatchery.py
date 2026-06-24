"""Second publish target ("port"): push approved/finished designs to the
maddhatchery.com storefront (the Nickel T's page) via its admin publish API.

Mirrors the Printify publisher (core/printify.py) but the "shop" is the
Madd Hatchery website. The site exposes:

    POST {MADDHATCHERY_API_URL}/api/admin/product   (header X-Admin-Token)
        body: {slug,name,category,description,price_cents,quantity,
               image_base64,image_ext}
    POST {MADDHATCHERY_API_URL}/api/admin/retire

Config (env):
    MADDHATCHERY_API_URL     default https://maddhatchery.com
    MADDHATCHERY_ADMIN_TOKEN required for --live publishes
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_API_URL = "https://maddhatchery.com"

# Map a concept/design onto one of the site's storefront categories.
SITE_CATEGORIES = ("nickel-tee", "madd-tee", "mug", "sticker")


def _slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(text).lower())).strip("-")


def site_category_for(concept, design=None) -> str:
    """Decide which storefront lane this design belongs in."""
    extra = getattr(concept, "extra", None) or {}
    dextra = getattr(design, "extra", None) or {}
    if extra.get("site_category") in SITE_CATEGORIES:
        return extra["site_category"]
    ptype = (extra.get("product_type") or dextra.get("product_type") or "").lower()
    if ptype in ("mug",):
        return "mug"
    if ptype in ("sticker",):
        return "sticker"
    lane = (getattr(concept, "lane", "") or "").lower()
    if "nickel" in lane or "novelty" in lane:
        return "nickel-tee"
    if "madd" in lane or "trish" in lane or "farm" in lane:
        return "madd-tee"
    return "nickel-tee"


class MaddhatcheryPublisher:
    def __init__(self, api_url: Optional[str] = None, admin_token: Optional[str] = None):
        self.api_url = (api_url or os.getenv("MADDHATCHERY_API_URL") or DEFAULT_API_URL).rstrip("/")
        self.admin_token = admin_token or os.getenv("MADDHATCHERY_ADMIN_TOKEN") or ""

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.api_url + path, data=body, method="POST",
            headers={"Content-Type": "application/json", "X-Admin-Token": self.admin_token},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"HTTP {e.code} from site: {detail}") from None

    def publish_design(self, concept, design, brand, *, category: Optional[str] = None,
                       price_cents: Optional[int] = None, quantity: int = 25,
                       dry_run: bool = False) -> Dict[str, Any]:
        """Push one design (its primary mockup) to the storefront."""
        cat = category or site_category_for(concept, design)
        # Clean storefront name: drop the "(visual brief)" parenthetical from the seed.
        raw_title = getattr(concept, "product_title", "") or ""
        name = re.sub(r"\s*\([^)]*\)\s*$", "", raw_title).strip() or raw_title.strip()
        slug = _slugify(name) or _slugify(getattr(concept, "slug", ""))
        desc = re.sub(r"\s*\([^)]*\)", "", (getattr(concept, "tagline", "") or "")).strip()
        price = price_cents
        if price is None:
            extra = getattr(concept, "extra", None) or {}
            price = extra.get("price_cents") or getattr(brand, "printify_price_cents", None) or 2800
        mockup = getattr(design, "mockup_path", None) if design else None

        payload: Dict[str, Any] = {
            "slug": slug, "name": name, "category": cat,
            "description": desc, "price_cents": int(price), "quantity": int(quantity),
        }
        if mockup and Path(mockup).exists():
            raw = Path(mockup).read_bytes()
            payload["image_base64"] = base64.b64encode(raw).decode("ascii")
            payload["image_ext"] = Path(mockup).suffix.lstrip(".").lower() or "png"

        if dry_run:
            return {"success": True, "dry_run": True, "slug": slug, "category": cat,
                    "name": name, "price_cents": int(price), "has_image": "image_base64" in payload}
        if not self.admin_token:
            raise RuntimeError("MADDHATCHERY_ADMIN_TOKEN not set — cannot publish live.")
        resp = self._post("/api/admin/product", payload)
        return {"success": bool(resp.get("ok")), "slug": slug, "category": cat,
                "product": resp.get("product"), "url": (resp.get("product") or {}).get("url")}

    def retire(self, slug: str, *, dry_run: bool = False) -> Dict[str, Any]:
        if dry_run:
            return {"success": True, "dry_run": True, "slug": slug}
        return self._post("/api/admin/retire", {"slug": slug})


def publish_brand_designs(brand, store, *, dry_run: bool = True, category: Optional[str] = None,
                          limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Publish every concept-with-a-mockup for a brand to the storefront.

    This is the design-driven path (works even before Printify listings exist).
    Records site_published back onto the matching listing's `extra` when possible.
    """
    pub = MaddhatcheryPublisher()
    out: List[Dict[str, Any]] = []
    concepts = store.list_concepts(brand=brand.slug)
    for concept in concepts:
        design = store.get_design(brand.slug, concept.slug)
        if not design or not getattr(design, "mockup_path", None):
            continue
        try:
            res = pub.publish_design(concept, design, brand, category=category, dry_run=dry_run)
            # best-effort: stamp site state onto any listing for this concept
            if not dry_run and res.get("success"):
                for l in store.list_listings(brand=brand.slug):
                    if l.concept_slug == concept.slug:
                        l.extra = l.extra or {}
                        l.extra["site_published"] = True
                        l.extra["site_url"] = res.get("url")
                        store.upsert_listing(l)
            out.append(res)
        except Exception as e:
            out.append({"success": False, "slug": concept.slug, "error": str(e)})
        if limit and len(out) >= limit:
            break
    return out
