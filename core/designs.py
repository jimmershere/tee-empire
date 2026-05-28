"""Design build + mockup compositing.

A Design carries the visual spec for a Concept. We render the *design art*
(via images.py) and composite it onto a flat shirt mockup so reviewers see
something product-like.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

try:
    from PIL import Image, ImageDraw
    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PIL_AVAILABLE = False

from . import images
from . import judge
from . import scoring
from .models import Brand, Concept, Design


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MOCKUP_DIR = DATA_DIR / "mockups"
MOCKUP_DIR.mkdir(parents=True, exist_ok=True)


def design_from_concept(brand: Brand, concept: Concept) -> Design:
    """Build a Design spec from a Concept, choosing the first palette/text-color combo."""
    palette = concept.suggested_colors or brand.palette or ["black"]
    shirt = palette[0]
    text = _pick_text_color(shirt)
    return Design(
        brand=brand.slug,
        concept_slug=concept.slug,
        design_text=concept.product_title,
        shirt_color=shirt,
        text_color=text,
        font_style="Bold Sans-Serif",
        design_notes=concept.design_prompt,
        source="compositor",
    )


def _pick_text_color(shirt: str) -> str:
    dark = {"black", "navy", "army", "charcoal", "vintage black", "heather dark gray",
            "heather cardinal", "red"}
    return "white" if shirt.lower() in dark else "black"


def build_mockup(brand: Brand, concept: Concept, design: Design, *,
                 dry_run: bool = False,
                 backend: Optional[str] = None) -> Design:
    """Render N variants of the design + composite each onto a t-shirt mockup.

    When the backend produces multiple variants (FLUX batch_size > 1), OCR
    each one against the expected headline, save them all, and mark the
    highest-scoring one as the primary mockup_path.

    Returns the updated Design.
    """
    variants, art_source = images.generate_design_variants(
        design.design_text, concept.design_prompt,
        backend=backend, text_color=_to_hex(design.text_color),
        shirt_color=_to_hex(design.shirt_color), dry_run=dry_run,
    )

    # Rank variants — Claude vision judge first, OCR fallback.
    judge_ranked = judge.rank_variants(variants, design.design_text, brand_voice=brand.voice)
    primary_idx, primary_score, primary_rationale = judge_ranked[0]
    # Convert to (idx, score) pairs so downstream save loop stays unchanged.
    ranked = [(idx, score) for idx, score, _ in judge_ranked]

    # Save mockups for all variants, primary gets the canonical filename.
    variant_paths: list[str] = []
    primary_path: Optional[Path] = None
    for rank, (orig_idx, score) in enumerate(ranked):
        suffix = "" if rank == 0 else f"__v{rank}"
        out_path = MOCKUP_DIR / f"{brand.slug}__{concept.slug}{suffix}.png"
        if _PIL_AVAILABLE:
            mockup = _compose_shirt_mockup(variants[orig_idx], design.shirt_color)
            mockup.save(out_path, format="PNG")
        else:  # pragma: no cover
            out_path.write_bytes(variants[orig_idx])
        variant_paths.append(str(out_path))
        if rank == 0:
            primary_path = out_path

    design.mockup_path = str(primary_path) if primary_path else None
    design.source = f"compositor:{art_source}"
    design.ocr_score = float(primary_score)
    design.variant_count = len(variants)
    design.variant_paths = variant_paths
    # Stash the judge rationale for the primary pick so HITL can show it.
    design.design_notes = (
        f"{concept.design_prompt[:200]}\n\n[judge] {primary_rationale}"
        if primary_rationale else concept.design_prompt
    )
    return design


def _compose_shirt_mockup(art_png: bytes, shirt_color: str) -> "Image.Image":
    """Composite design art onto a flat t-shirt silhouette."""
    canvas_w, canvas_h = 1600, 1800
    bg = Image.new("RGB", (canvas_w, canvas_h), (245, 245, 240))
    shirt_rgb = _parse_color(shirt_color)
    shirt = _draw_shirt(canvas_w, canvas_h, shirt_rgb)
    bg.paste(shirt, (0, 0), shirt)
    art = Image.open(BytesIO(art_png)).convert("RGBA")
    art_w = int(canvas_w * 0.42)
    art_h = int(art.height * (art_w / art.width))
    art = art.resize((art_w, art_h), Image.LANCZOS)
    pos = ((canvas_w - art_w) // 2, int(canvas_h * 0.32))
    bg.paste(art, pos, art if art.mode == "RGBA" else None)
    return bg


def _draw_shirt(w: int, h: int, color: Tuple[int, int, int]) -> "Image.Image":
    """Approximate t-shirt silhouette using polygons."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = w // 2
    body_top = int(h * 0.22)
    body_bot = int(h * 0.92)
    body_left = int(w * 0.22)
    body_right = int(w * 0.78)
    # body
    d.polygon([
        (body_left, body_top + 60),
        (cx - 130, body_top),
        (cx - 60, body_top + 30),
        (cx + 60, body_top + 30),
        (cx + 130, body_top),
        (body_right, body_top + 60),
        (body_right + 90, body_top + 220),
        (body_right - 20, body_top + 280),
        (body_right - 20, body_bot),
        (body_left + 20, body_bot),
        (body_left + 20, body_top + 280),
        (body_left - 90, body_top + 220),
    ], fill=color + (255,))
    # neckline
    d.ellipse([cx - 90, body_top - 10, cx + 90, body_top + 60], fill=(245, 245, 240, 255))
    return img


def _parse_color(c: str) -> Tuple[int, int, int]:
    return images._parse_color(c)  # type: ignore[attr-defined]


def _to_hex(c: str) -> str:
    r, g, b = _parse_color(c)
    return f"#{r:02X}{g:02X}{b:02X}"
