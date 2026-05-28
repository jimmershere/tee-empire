"""Design build + mockup compositing.

A Design carries the visual spec for a Concept. We render the *design art*
(via images.py) and composite it onto a flat shirt mockup so reviewers see
something product-like.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PIL_AVAILABLE = False


# Monospace fonts to try for code overlays (first hit wins).
_MONO_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
)

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


def overlay_text_panel(image_bytes: bytes, *,
                       text: str,
                       region: Tuple[float, float, float, float] = (0.13, 0.08, 0.74, 0.30),
                       panel_color: str = "#000000",
                       border_color: str = "#D49A2C",
                       border_width: int = 6,
                       text_color: str = "#FFFFFF",
                       padding: int = 18,
                       line_spacing: float = 1.15) -> bytes:
    """Paste a filled rectangle + monospace text on top of an image.

    Used by ``build_mockup`` when a Concept's ``extra["text_overlay"]`` is set.
    Lets us guarantee verbatim code/long-text rendering (which image models
    can't reliably do for dense content like brainfuck source) while still
    leveraging the model for the surrounding art.

    Args:
        image_bytes: raw PNG/JPG bytes from the model.
        text: exact text to render inside the panel. Will be character-wrapped
              to fit the panel width at the largest legible monospace size.
        region: (x, y, w, h) as fractions of image size. Default = top-third
                centered, leaving room for a mascot below.
    """
    if not _PIL_AVAILABLE:
        return image_bytes
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    W, H = img.size
    x = int(region[0] * W)
    y = int(region[1] * H)
    w = int(region[2] * W)
    h = int(region[3] * H)
    draw = ImageDraw.Draw(img)
    # Draw filled panel + border
    panel_rgb = _parse_color(panel_color)
    border_rgb = _parse_color(border_color)
    draw.rectangle([x, y, x + w, y + h], fill=panel_rgb,
                   outline=border_rgb, width=border_width)
    # Pick a monospace font
    font_path = next((p for p in _MONO_FONTS if Path(p).exists()), None)
    avail_w = w - 2 * padding
    avail_h = h - 2 * padding
    # Auto-size the text to fit the panel
    font_size = max(int(h * 0.10), 8)
    text_rgb = _parse_color(text_color)
    lines: List[str] = []
    while font_size >= 6:
        if font_path:
            font = ImageFont.truetype(font_path, font_size)
        else:
            font = ImageFont.load_default()
        # measure mono char width using "0" as representative
        try:
            char_w = font.getlength("0")
        except AttributeError:
            char_w = font_size * 0.6
        chars_per_line = max(1, int(avail_w / char_w))
        lines = _wrap_fixed_width(text, chars_per_line)
        line_h = int(font_size * line_spacing)
        if line_h * len(lines) <= avail_h:
            break
        font_size -= 1
    # Draw the text
    text_x = x + padding
    text_y = y + padding
    for line in lines:
        draw.text((text_x, text_y), line, font=font, fill=text_rgb)
        text_y += int(font_size * line_spacing)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _wrap_fixed_width(text: str, width: int) -> List[str]:
    """Hard-wrap a string into chunks of exactly ``width`` chars.

    Used for code where any character (including whitespace) is meaningful, so
    word-wrapping is wrong. Keeps source verbatim.
    """
    if width <= 0:
        return [text]
    return [text[i:i + width] for i in range(0, len(text), width)] or [""]


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

    # If the concept declared a text overlay, paint it onto every variant
    # BEFORE judging so the judge sees the final design. Used for concepts
    # whose art carries verbatim code/long-text that image models can't
    # render accurately (e.g. brainfuck source).
    overlay = (concept.extra or {}).get("text_overlay") if hasattr(concept, "extra") else None
    if overlay and isinstance(overlay, dict) and overlay.get("text"):
        kwargs: Dict[str, Any] = {"text": overlay["text"]}
        if "region" in overlay:
            kwargs["region"] = tuple(overlay["region"])
        for k in ("panel_color", "border_color", "text_color",
                  "border_width", "padding", "line_spacing"):
            if k in overlay:
                kwargs[k] = overlay[k]
        variants = [overlay_text_panel(v, **kwargs) for v in variants]

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
