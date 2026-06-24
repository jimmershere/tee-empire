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
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
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

# Font catalog for literal text placements. Each entry: stable key, friendly
# label, UI category (drives the dropdown's optgroups), and candidate file paths
# (first existing + PIL-loadable wins). Discovered by scanning the installed
# font set; effect-only layers (Biker Whiskey "FX"/"Texture"), dingbat/ornament
# faces, and empties (Loyalty Chicano .ttf) are intentionally omitted so every
# offered font actually renders legible letters.
_FONT_CATALOG = [
    ("bold_sans", "Bold Sans", "Clean",
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")),
    ("serif", "Serif", "Clean",
        ("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf")),
    ("slab_mono", "Slab / Mono", "Clean",
        ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf")),
    ("condensed", "Condensed", "Clean",
        ("/usr/share/fonts/opentype/urw-base35/NimbusSansNarrow-Bold.otf",)),
    ("brother_gothic", "Brother Gothic", "Bold / Athletic",
        ("/usr/share/fonts/Brother-Gothic-95736799/Brother Gothic.otf",)),
    ("hero_force", "Hero Force", "Bold / Athletic", ("/usr/share/fonts/Hero Force.otf",)),
    ("skin_hero", "Skin Hero", "Bold / Athletic", ("/usr/share/fonts/Skin Hero.otf",)),
    ("atlas_celeste", "Atlas Celeste", "Bold / Athletic", ("/usr/share/fonts/Atlas Celeste.otf",)),
    ("positive_sixties", "Positive Sixties", "Bold / Athletic",
        ("/usr/share/fonts/Positive Sixties Regular.otf",)),
    ("dolkern", "Dolkern", "Bold / Athletic", ("/usr/share/fonts/Dolkern.otf",)),
    ("biker_whiskey", "Biker Whiskey", "Distressed",
        ("/usr/share/fonts/Biker-Whiskey-11203675/BikerWhiskey Regular.otf",)),
    ("biker_whiskey_rough", "Biker Whiskey Rough", "Distressed",
        ("/usr/share/fonts/Biker-Whiskey-11203675/BikerWhiskeyRough Regular.otf",)),
    ("bruised", "Bruised", "Distressed", ("/usr/share/fonts/Bruised.otf",)),
    ("rusticle", "Rusticle", "Distressed", ("/usr/share/fonts/Rusticle.otf",)),
    ("merchant_ledger", "Merchant Ledger", "Distressed", ("/usr/share/fonts/Merchant Ledger.otf",)),
    ("morgan_tattoo", "Morgan Tattoo", "Distressed", ("/usr/share/fonts/Morgan tattoo.otf",)),
    ("morgan_tattoo_italic", "Morgan Tattoo Italic", "Distressed",
        ("/usr/share/fonts/Morgan tattoo italic.otf",)),
    ("raven_black", "Raven Black", "Distressed", ("/usr/share/fonts/Raven Black Regular.otf",)),
    ("loyalty_chicano", "Loyalty Chicano", "Script", ("/usr/share/fonts/Loyalty Chicano.otf",)),
    ("emilia_luck", "Emilia Luck", "Script", ("/usr/share/fonts/Emilia Luck.otf",)),
    ("my_wednesday", "My Wednesday Nights", "Script", ("/usr/share/fonts/My Wednesday Night.otf",)),
    ("taylor_moore", "Taylor Moore", "Script", ("/usr/share/fonts/Taylor Moore.otf",)),
    ("bavose", "Bavose", "Script", ("/usr/share/fonts/Bavose Regular.otf",)),
    ("beltino", "Beltino", "Script", ("/usr/share/fonts/Beltino-142124784/Beltino Regular.otf",)),
    ("litoriu", "Litoriu", "Script", ("/usr/share/fonts/Litoriu.otf",)),
    ("blistao", "Blistao", "Script", ("/usr/share/fonts/Blistao.otf",)),
    ("midnight_minutes", "Midnight Minutes", "Script", ("/usr/share/fonts/Midnightminutes.otf",)),
    ("amstrong", "Amstrong", "Script", ("/usr/share/fonts/Amstrong.otf",)),
    ("retro_magic", "Retro Magic", "Script", ("/usr/share/fonts/Retro Magic.otf",)),
    ("perfecto_enough", "Perfecto Enough", "Script", ("/usr/share/fonts/Perfecto Enough.otf",)),
    ("bethinae", "Bethinae", "Script", ("/usr/share/fonts/Bethinae Regular.otf",)),
    ("lucky_comic", "Lucky Comic", "Comic / Fun", ("/usr/share/fonts/Lucky Comic.otf",)),
    ("comic_bubble", "Comic Bubble", "Comic / Fun", ("/usr/share/fonts/Comicbubble Regular.otf",)),
    ("asian_hiro", "Asian Hiro", "Comic / Fun", ("/usr/share/fonts/Asian Hiro.otf",)),
]

_FONT_CACHE: Optional[List[Dict[str, str]]] = None

TEXT_COLORS = {
    "white": "#ffffff", "black": "#111111", "red": "#c0392b",
    "navy": "#1c2b4a", "gold": "#d4af37", "grey": "#8a8a8a",
}


def _font_loadable(path: str) -> bool:
    if not _PIL_AVAILABLE:
        return False
    try:
        ImageFont.truetype(path, 32)
        return True
    except Exception:
        return False


def available_text_fonts() -> List[Dict[str, str]]:
    """Catalog fonts that are present on disk AND loadable by PIL.

    Returns a list of ``{key, label, category, path}`` in catalog order. Result
    is cached for the process — the installed font set doesn't change mid-run.
    """
    global _FONT_CACHE
    if _FONT_CACHE is not None:
        return _FONT_CACHE
    out: List[Dict[str, str]] = []
    for key, label, category, paths in _FONT_CATALOG:
        path = next((p for p in paths if Path(p).exists() and _font_loadable(p)), None)
        if path:
            out.append({"key": key, "label": label, "category": category, "path": path})
    _FONT_CACHE = out
    return out


def font_path_for(font_key: str) -> Optional[str]:
    """Resolve a font key to a usable file path, falling back to the first
    available catalog font (Bold Sans)."""
    fonts = available_text_fonts()
    for f in fonts:
        if f["key"] == font_key:
            return f["path"]
    return fonts[0]["path"] if fonts else None

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


def _logo_circle(img: "Image.Image", bg_tolerance: int) -> Optional[Tuple[float, float, float]]:
    """Fit the logo's outer circle: (center_x, center_y, radius) in pixels.

    The radius is the distance from the logo's center to its OUTERMOST artwork —
    i.e. the outer edge of a badge's border ring, which can bulge past the square's
    inscribed circle into the corners. Cropping to ``max(w, h) / 2`` (the inscribed
    radius) would slice that border off on all sides; fitting to the true outer
    radius keeps the whole ring.

    Foreground = the alpha channel when the art is transparent, else any pixel that
    differs from the median corner color by more than the tolerance. A 1px erosion
    drops isolated specks so a stray hot pixel can't inflate the radius. Returns
    None if numpy is unavailable or no foreground is found (caller falls back).
    """
    try:
        import numpy as np
    except Exception:
        return None
    a = np.asarray(img)
    h, w = a.shape[:2]
    alpha = a[..., 3]
    if int(alpha.min()) < 255:  # genuine transparency
        fg = alpha > 16
    else:
        corners = np.array([a[0, 0, :3], a[0, -1, :3], a[-1, 0, :3], a[-1, -1, :3]],
                           dtype=np.int32)
        bg = np.median(corners, axis=0)
        rgb = a[..., :3].astype(np.int32)
        dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
        fg = dist > max(bg_tolerance, 30)
    if not fg.any():
        return None
    eroded = np.asarray(
        Image.fromarray((fg * 255).astype("uint8")).filter(ImageFilter.MinFilter(3))) > 0
    if not eroded.any():
        eroded = fg
    ys, xs = np.where(eroded)
    cx = (float(xs.min()) + float(xs.max())) / 2.0
    cy = (float(ys.min()) + float(ys.max())) / 2.0
    radius = float(np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2).max())
    return cx, cy, radius


def circular_trim(image_bytes: bytes, *, pad_ratio: float = 0.02,
                  bg_tolerance: int = 14, supersample: int = 4) -> bytes:
    """Crop art down to a clean sphere: no square edges, transparent corners.

    Trims inward from the canvas edges to the logo's OUTER border, then multiplies
    in an antialiased circular alpha mask sized to that border (plus a hairline
    epsilon so the outermost ring isn't shaved) so the corners vanish but the whole
    logo survives. Used for logo drops (e.g. local81) whose Printify print image
    must read as a round badge. No-op if Pillow is unavailable.
    """
    if not _PIL_AVAILABLE:
        return image_bytes
    img = Image.open(BytesIO(image_bytes)).convert("RGBA")
    circle = _logo_circle(img, bg_tolerance)
    if circle is None:
        w, h = img.size
        cx, cy, radius = (w - 1) / 2.0, (h - 1) / 2.0, max(w, h) / 2.0
    else:
        cx, cy, radius = circle
    radius += max(1.0, radius * 0.004)         # hairline bias so the outer ring stays whole
    pad = int(radius * pad_ratio)
    side = int(round(2 * (radius + pad)))
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    center = side / 2.0
    out.paste(img, (int(round(center - cx)), int(round(center - cy))), img)
    big = side * supersample
    mask = Image.new("L", (big, big), 0)
    rc, cc = radius * supersample, center * supersample
    ImageDraw.Draw(mask).ellipse([cc - rc, cc - rc, cc + rc, cc + rc], fill=255)
    mask = mask.resize((side, side), Image.BILINEAR)   # bilinear: no LANCZOS ring-shave
    out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))
    buf = BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def render_text_png(text: str, *, font_key: str = "bold_sans", color: str = "white",
                    canvas: Tuple[int, int] = (1600, 2000),
                    outline: bool = False) -> bytes:
    """Render literal ``text`` as a crisp, transparent PNG.

    Unlike AI image edits, this reproduces the EXACT words in the chosen font —
    used for stamping text onto a secondary print placement (tee back, sleeve).
    Splits on newlines, auto-fits the largest size that fits the canvas, and
    centers every line. ``outline`` adds a dark stroke so light text stays
    legible on light garments.
    """
    if not _PIL_AVAILABLE:
        raise RuntimeError("Pillow is required for text rendering (pip install pillow).")
    W, H = canvas
    fill = _parse_color(TEXT_COLORS.get(color, color))
    font_path = font_path_for(font_key)
    lines = [ln for ln in (text.splitlines() or [text]) if ln != ""] or [text]
    pad = int(min(W, H) * 0.08)
    max_w, max_h = W - 2 * pad, H - 2 * pad

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    size = int(H * 0.5)
    font = None
    line_h = 0
    while size >= 8:
        font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
        widths, heights = [], []
        for ln in lines:
            bb = draw.textbbox((0, 0), ln, font=font)
            widths.append(bb[2] - bb[0]); heights.append(bb[3] - bb[1])
        line_h = int(max(heights) * 1.3)
        if max(widths) <= max_w and line_h * len(lines) <= max_h:
            break
        size -= 4

    stroke = max(2, size // 36) if outline else 0
    total_h = line_h * len(lines)
    y = (H - total_h) // 2 + line_h // 2
    for ln in lines:
        draw.text((W // 2, y), ln, font=font, fill=fill, anchor="mm",
                  stroke_width=stroke, stroke_fill=(20, 20, 20, 255) if stroke else None)
        y += line_h
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
                  backend: Optional[str] = None,
                  product_type: Optional[str] = None) -> Design:
    """Render N variants of the design + composite each onto a product mockup.

    product_type: shirt (default), mug, sticker, poster.
    Supports reviewer-driven text/tags/overlays in the local gate.

    When the backend produces multiple variants (FLUX batch_size > 1), OCR
    each one against the expected headline, save them all, and mark the
    highest-scoring one as the primary mockup_path.

    Returns the updated Design.
    """
    pt = product_type or (concept.extra or {}).get("product_type") or "shirt"
    # Brand-mascot reference (img2img): if the brand ships a character fixture,
    # use it for brand-character lanes (e.g. madd_style) so the mascot stays
    # consistent. Novelty lanes (nickel/drops) stay text-to-image.
    reference_png = None
    try:
        from empire.core import brands as _brands_mod
        lane = (getattr(concept, "lane", "") or "").lower()
        cextra = getattr(concept, "extra", None) or {}
        override = cextra.get("character_ref")  # per-concept reference (e.g. an alt mascot)
        if override and Path(override).exists():
            reference_png = Path(override).read_bytes()
        else:
            char_path = _brands_mod.brand_dir(brand.slug) / "fixtures" / "character.png"
            if char_path.exists() and not any(k in lane for k in ("nickel", "novelty", "drops")):
                reference_png = char_path.read_bytes()
    except Exception:
        reference_png = None
    variants, art_source = images.generate_design_variants(
        design.design_text, concept.design_prompt,
        backend=backend, text_color=_to_hex(design.text_color),
        shirt_color=_to_hex(design.shirt_color), reference_png=reference_png, dry_run=dry_run,
    )

    # If the concept declared a text overlay, paint it onto every variant
    # BEFORE judging so the judge sees the final design.
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
    ranked = [(idx, score) for idx, score, _ in judge_ranked]

    # Save mockups for all variants, primary gets the canonical filename.
    variant_paths: list[str] = []
    primary_path: Optional[Path] = None
    for rank, (orig_idx, score) in enumerate(ranked):
        suffix = "" if rank == 0 else f"__v{rank}"
        out_path = MOCKUP_DIR / f"{brand.slug}__{concept.slug}{suffix}.png"
        if _PIL_AVAILABLE:
            if pt == "mug":
                mockup = _compose_mug_mockup(variants[orig_idx], design.shirt_color)
            elif pt == "sticker":
                mockup = _compose_sticker_mockup(variants[orig_idx])
            elif pt == "poster":
                mockup = _compose_poster_mockup(variants[orig_idx])
            else:
                mockup = _compose_shirt_mockup(variants[orig_idx], design.shirt_color)
            mockup.save(out_path, format="PNG")
        else:  # pragma: no cover
            out_path.write_bytes(variants[orig_idx])
        variant_paths.append(str(out_path))
        if rank == 0:
            primary_path = out_path

    design.mockup_path = str(primary_path) if primary_path else None
    design.source = f"compositor:{art_source}:{pt}"
    design.ocr_score = float(primary_score)
    design.variant_count = len(variants)
    design.variant_paths = variant_paths
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


def _compose_mug_mockup(art_png: bytes, mug_color: str = "#222") -> "Image.Image":
    """Simple mug mockup: cylinder body + handle + centered art (for 11-15oz)."""
    canvas_w, canvas_h = 1400, 1200
    bg = Image.new("RGB", (canvas_w, canvas_h), (245, 245, 240))
    mug_rgb = _parse_color(mug_color)
    # body (rounded rect)
    d = ImageDraw.Draw(bg)
    body = [300, 200, 1100, 1000]
    d.rounded_rectangle(body, radius=80, fill=mug_rgb + (255,) if hasattr(d, 'rounded_rectangle') else mug_rgb)
    # handle
    d.ellipse([1050, 350, 1250, 650], outline=mug_rgb, width=28)
    d.ellipse([1080, 380, 1220, 620], fill=(245, 245, 240))
    # art centered on body
    art = Image.open(BytesIO(art_png)).convert("RGBA")
    aw = int(420)
    ah = int(art.height * (aw / art.width))
    art = art.resize((aw, ah), Image.LANCZOS)
    pos = (int((body[0] + body[2]) / 2 - aw / 2), int((body[1] + body[3]) / 2 - ah / 2))
    bg.paste(art, pos, art if art.mode == "RGBA" else None)
    return bg


def _compose_sticker_mockup(art_png: bytes) -> "Image.Image":
    """Circular sticker / die-cut style with white border."""
    canvas = 1100
    bg = Image.new("RGB", (canvas, canvas), (245, 245, 240))
    d = ImageDraw.Draw(bg)
    cx = canvas // 2
    # outer white border
    d.ellipse([50, 50, canvas-50, canvas-50], fill=(255, 255, 255))
    # inner circle for art
    d.ellipse([90, 90, canvas-90, canvas-90], fill=(30, 30, 30))
    art = Image.open(BytesIO(art_png)).convert("RGBA")
    aw = int(canvas * 0.72)
    ah = int(art.height * (aw / art.width))
    art = art.resize((aw, ah), Image.LANCZOS)
    pos = ((canvas - aw) // 2, (canvas - ah) // 2)
    bg.paste(art, pos, art if art.mode == "RGBA" else None)
    # subtle cut line
    d.ellipse([70, 70, canvas-70, canvas-70], outline=(200, 200, 200), width=3)
    return bg


def _compose_poster_mockup(art_png: bytes) -> "Image.Image":
    """Poster / print mockup: white margin + art centered."""
    canvas_w, canvas_h = 1200, 1600
    bg = Image.new("RGB", (canvas_w, canvas_h), (250, 250, 245))
    d = ImageDraw.Draw(bg)
    # frame
    d.rectangle([40, 40, canvas_w-40, canvas_h-40], outline=(60, 60, 60), width=8)
    art = Image.open(BytesIO(art_png)).convert("RGBA")
    aw = int(canvas_w * 0.82)
    ah = int(art.height * (aw / art.width))
    if ah > canvas_h * 0.82:
        ah = int(canvas_h * 0.82)
        aw = int(art.width * (ah / art.height))
    art = art.resize((aw, ah), Image.LANCZOS)
    pos = ((canvas_w - aw) // 2, (canvas_h - ah) // 2)
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
