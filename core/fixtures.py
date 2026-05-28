"""Import concepts/designs from the original earl-biggers source tree.

Idempotent: re-running just refreshes rows via the same (brand, slug) primary
key. Designed to bootstrap the empire DB without re-generating from API.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

from .brands import load_brand
from .concepts import slugify
from .models import Concept, Design
from .store import Store


def import_earl_biggers_from_path(source_root: Path, store: Store) -> Tuple[int, int]:
    """Import concepts + designs from the legacy earl-biggers folder. Returns (concepts, designs)."""
    brand = load_brand("earl_biggers")
    concepts_dir = source_root / "concepts"
    designs_dir = source_root / "designs"
    concepts_imported = 0
    designs_imported = 0

    if concepts_dir.exists():
        for path in sorted(concepts_dir.glob("*.json")):
            raw = json.loads(path.read_text())
            c = _legacy_concept_to_model(raw, path, brand_slug="earl_biggers")
            store.upsert_concept(c)
            concepts_imported += 1

    if designs_dir.exists():
        for path in sorted(designs_dir.glob("*.json")):
            raw = json.loads(path.read_text())
            d, concept = _legacy_design_to_model(raw, brand_slug="earl_biggers")
            if concept and not store.get_concept("earl_biggers", concept.slug):
                store.upsert_concept(concept)
                concepts_imported += 1
            store.upsert_design(d)
            designs_imported += 1

    return concepts_imported, designs_imported


def _legacy_concept_to_model(raw: Dict, path: Path, brand_slug: str) -> Concept:
    # Two shapes exist in the legacy data:
    #   (A) old "id/shirt_copy/tagline/notes/category" form
    #   (B) new "brand_lane/input_handle/slug/product_title/..." form (from concept_generator output)
    if "product_title" in raw and "design_prompt" in raw and "slug" in raw:
        lane = str(raw.get("brand_lane") or raw.get("lane") or "biggers").lower().replace("-", "_")
        slug = slugify(f"{brand_slug}-{lane}-{raw['product_title']}")
        return Concept(
            brand=brand_slug,
            lane=lane,
            slug=slug,
            input_handle=str(raw.get("input_handle") or raw.get("product_title")),
            product_title=str(raw["product_title"]),
            tagline=str(raw.get("tagline", "")),
            design_prompt=str(raw["design_prompt"]),
            suggested_colors=list(raw.get("suggested_colors", [])),
            tags=list(raw.get("tags", [])),
            safety_notes=list(raw.get("safety_notes", [])),
            source=str(raw.get("source", "imported")),
            extra={"legacy_path": str(path)},
        )
    # Form A
    handle = str(raw.get("shirt_copy") or raw.get("id") or path.stem)
    lane = str(raw.get("category") or "biggers").lower().replace("-", "_")
    title = f"Earl Biggers: {raw.get('id', path.stem).upper()}"
    slug = slugify(f"{brand_slug}-{lane}-{title}")
    return Concept(
        brand=brand_slug,
        lane=lane,
        slug=slug,
        input_handle=handle.replace("\n", " / "),
        product_title=title,
        tagline=str(raw.get("tagline", "Raw Earl Biggers linework for the brave.")),
        design_prompt=str(raw.get("notes") or f"Bold typographic tee built around '{handle}'."),
        suggested_colors=[str(raw.get("shirt_color") or "black")],
        tags=["earl biggers", lane.replace("_", " "), slugify(handle)],
        safety_notes=["HITL review required before anything live."],
        source="imported",
        extra={"legacy_path": str(path), "raw_id": raw.get("id")},
    )


def _legacy_design_to_model(raw: Dict, brand_slug: str) -> Tuple[Design, Concept]:
    """Legacy designs dir contains both design specs AND the concept text. Synthesize both."""
    lane = str(raw.get("category", "biggers")).lower().replace("-", "_")
    handle = str(raw.get("design_text") or raw.get("id") or "design")
    title = str(raw.get("title") or f"Earl Biggers: {raw.get('id', '').upper()}")
    slug = slugify(f"{brand_slug}-{lane}-{title}")
    concept = Concept(
        brand=brand_slug,
        lane=lane,
        slug=slug,
        input_handle=handle,
        product_title=title,
        tagline=str(raw.get("tagline", "")),
        design_prompt=str(raw.get("design_notes", "")),
        suggested_colors=[str(raw.get("shirt_color", "black"))],
        tags=list(raw.get("etsy_tags", [])),
        safety_notes=["HITL review required."] if raw.get("hitl_review_needed") else [],
        source="imported-design",
        extra={"raw_id": raw.get("id"), "lane": lane},
    )
    design = Design(
        brand=brand_slug,
        concept_slug=slug,
        design_text=str(raw.get("design_text", "")),
        shirt_color=str(raw.get("shirt_color", "black")),
        text_color=str(raw.get("text_color", "white")),
        font_style=str(raw.get("font_style", "Bold Sans-Serif")),
        design_notes=str(raw.get("design_notes", "")),
        source="imported",
    )
    return design, concept
