"""Brand loading. One brand = one directory under empire/brands/<slug>/."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .models import Brand

BRANDS_ROOT = Path(__file__).resolve().parents[1] / "brands"


def brand_dir(slug: str) -> Path:
    return BRANDS_ROOT / slug


def load_brand(slug: str) -> Brand:
    d = brand_dir(slug)
    cfg_path = d / "brand.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"Brand config missing: {cfg_path}")
    raw = yaml.safe_load(cfg_path.read_text())
    raw.setdefault("slug", slug)
    return Brand(**raw)


def list_brand_slugs() -> List[str]:
    if not BRANDS_ROOT.exists():
        return []
    return sorted(p.name for p in BRANDS_ROOT.iterdir() if p.is_dir() and (p / "brand.yaml").exists())


def load_all_brands() -> Dict[str, Brand]:
    return {slug: load_brand(slug) for slug in list_brand_slugs()}


def lane_seeds(brand_slug: str, lane: str) -> List[str]:
    """Load seed handles for a brand+lane. JSON list at brands/<brand>/lanes/<lane>.json."""
    p = brand_dir(brand_slug) / "lanes" / f"{lane}.json"
    if not p.exists():
        return []
    raw = json.loads(p.read_text())
    if isinstance(raw, dict):
        return list(raw.get("seeds", []))
    return list(raw)


def fixture_dir(brand_slug: str) -> Path:
    return brand_dir(brand_slug) / "fixtures"
