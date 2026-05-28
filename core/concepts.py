"""Multi-brand concept generation.

Pluggable backends:
  - "template" (always available, deterministic, brand-voice aware)
  - "xai"      (Grok via x.ai responses API, if XAI_API_KEY set)

A "concept" is the marketing-side spec: title, tagline, design prompt, tags.
A "design" (see designs.py) is the visual spec built from a concept.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Brand, Concept

XAI_ENDPOINT = "https://api.x.ai/v1/responses"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "concept"


def placeholder_mockup_url(title: str, lane: str) -> str:
    label = urllib.parse.quote(f"{lane}: {title}"[:70])
    return f"https://placehold.co/1200x1500/png?text={label}"


# ---------------- XAI backend ----------------
class XAIClient:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("XAI_API_KEY") or _read_secret_env("XAI_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def generate(self, brand: Brand, handle: str, lane: str) -> Optional[Dict[str, Any]]:
        if not self.configured:
            return None
        prompt = (
            f"You are a merch concept writer for the brand '{brand.name}'. "
            f"Brand voice: {brand.voice}. Niches: {', '.join(brand.niches)}. "
            f"Lane: {lane}. Input handle/meme: {handle}. "
            "Return JSON only with keys: product_title, tagline, design_prompt, "
            "suggested_colors (list), tags (list), safety_notes (list). "
            "Style: punchy print-on-demand tee copy, not essay prose. "
            "Avoid actual slurs, copyrighted brands, or targeted harassment."
        )
        payload = {
            "model": "grok-4.20-reasoning",
            "input": prompt,
            "text": {"format": {"type": "json_object"}},
        }
        req = urllib.request.Request(
            XAI_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
            return None
        try:
            if isinstance(raw.get("output_text"), str):
                return json.loads(raw["output_text"])
            for item in raw.get("output", []):
                for content in item.get("content", []):
                    text = content.get("text")
                    if text:
                        return json.loads(text)
        except (KeyError, TypeError, json.JSONDecodeError):
            return None
        return None


def _read_secret_env(name: str) -> Optional[str]:
    for path in (Path.home() / ".openclaw" / "secrets" / "xai.env",
                 Path(__file__).resolve().parents[1] / ".env"):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ---------------- Template backend ----------------
def template_concept(brand: Brand, handle: str, lane: str) -> Dict[str, Any]:
    """Brand-voice-aware deterministic concept. Always works, no API."""
    cleaned = handle.strip()
    palette = brand.palette or ["black", "white", "navy", "charcoal"]
    voice = brand.voice or "punchy"
    title = _voiced_title(brand, lane, cleaned)
    tagline = _voiced_tagline(brand, lane, cleaned)
    design_prompt = _voiced_design_prompt(brand, lane, cleaned, palette)
    tags = _brand_tags(brand, lane, cleaned)
    safety = _safety_for(brand, lane)
    return {
        "product_title": title,
        "tagline": tagline,
        "design_prompt": design_prompt,
        "suggested_colors": palette[:5],
        "tags": tags,
        "safety_notes": safety,
    }


def _voiced_title(brand: Brand, lane: str, handle: str) -> str:
    lane_l = lane.lower()
    # force_multipliers seeds carry their own punctuation (×, *, Σ, etc.) — pass through.
    if lane_l in {"force_multipliers", "force-multipliers"}:
        return handle
    # biggers — the merged Earl Biggers grown-up lane. Brand-prefixed title.
    if lane_l == "biggers":
        return f"{brand.name}: {handle}"
    return f"{handle}"


def _voiced_tagline(brand: Brand, lane: str, handle: str) -> str:
    lane_l = lane.lower()
    if brand.slug == "earl_biggers" and lane_l in {"force_multipliers", "force-multipliers"}:
        # Sarcastic deadpan tech-tone for the nerdy/coder buyer.
        return f"Optimized for chaos. Compiled with spite. {handle}."
    if brand.slug == "earl_biggers":
        return f"A wink, a gasp, and a deadpan grin: {handle}."
    if brand.slug == "nickle_ts":
        return f"Worn-in. RI-proud. {handle}."
    return f"{handle} — {brand.name}."


def _voiced_design_prompt(brand: Brand, lane: str, handle: str, palette: List[str]) -> str:
    """Build a rich design prompt combining illustrative motif + bold legible typography.

    Written assuming the image model can render text reasonably (FLUX-schnell or
    similar). For SDXL-class models you'd want to fall back to texture-only and
    composite the text in PIL.
    """
    lane_l = lane.lower()
    primary = palette[0] if palette else "black"
    # IMPORTANT: mention the headline phrase EXACTLY ONCE in the prompt to avoid
    # FLUX duplicating it in the rendered text. Visual style guidance must not
    # repeat the phrase.
    if brand.slug == "earl_biggers" and lane_l in {"force_multipliers", "force-multipliers"}:
        return (
            f'Print-ready t-shirt graphic on a {primary} background. The headline text reads exactly "{handle}" '
            "in a chunky monospace coder/terminal font (Source Code Pro, IBM Plex Mono, square-pixel sans). "
            "Integrate the asterisk (*) as a multiplication-symbol motif — small starbursts in the negative "
            "space or scattered like syntax highlighting. Below the headline, add one subtle code-comment "
            "flourish in the same monospace font, slightly smaller, like '// optimized for chaos' or "
            "'/* working as intended */'. Single-color screenprint look, white ink with a thin amber or "
            "phosphor-green accent (vintage CRT terminal aesthetic). Subtle paper-grain distress. "
            "Sarcastic deadpan tech-humor tone for the developer/engineer/STEM-nerd buyer. "
            "Marketplace-safe, no copyrighted brands or characters."
        )
    if brand.slug == "earl_biggers" and lane_l == "biggers":
        # Merged grown-up lane: covers brand-name wordplay, ironic anger, burnout grit, deadpan
        # deflection. Prompt is intentionally flexible — nano-banana-2 picks the right visual
        # treatment based on what the headline calls for.
        return (
            f'Print-ready t-shirt graphic on a {primary} background. Earl Biggers brand: adult-humor '
            f'deadpan grit, marketplace-safe. The headline reads exactly: "{handle}" in tall bold '
            "uppercase sans-serif lettering, white ink, slight screenprint ink-bleed. Pair the "
            "headline with ONE supporting visual that fits the phrase: a bold-line cartoon mascot "
            "(weary skeleton, drained cartoon animal, cracked coffee mug, wilted dumbbell, beat-up "
            "boxing glove), OR a small ironic badge/seal/stamp graphic, OR — if the headline is "
            "pure brand wordplay ('Biggers' wordplay etc.) — favor minimal typography with a small "
            "asterisk/starburst accent. Vintage screenprint texture, 1-2 flat colors, optional "
            "single muted red or yellow accent. Centered chest-print composition. No copyrighted "
            "characters or brands."
        )
    if brand.slug == "earl_biggers":
        # brocode / fellowship lanes — bar-room signage
        return (
            f'Print-ready t-shirt graphic on a {primary} background. Hand-painted bar-room signage '
            f'style with the headline "{handle}" set as the dominant chunky condensed display lettering '
            "in white. A single bold illustrated motif (winking neon sign, vintage matchbook, "
            "punching fist, flaming heart, or beer-mug toast — pick one) sits tucked into the "
            "negative space below. 2-3 flat screenprint colors, halftone texture, marketplace-safe."
        )
    if brand.slug == "nickle_ts":
        return (
            f'Print-ready t-shirt graphic on a {primary} background. Hand-drawn 1950s diner / vintage '
            f'postcard linocut style. Headline text "{handle}" set in a chunky vintage serif. Below '
            "the headline, a single warm illustration anchoring the composition (a vintage coffee-milk "
            "bottle, a Del's lemon cup, a steaming bowl of soup, a quahog shell, a stylized RI state "
            "outline, or a worn bar stool — pick one). Warm muted screenprint colors, paper grain, "
            "family-friendly tone, evokes Rhode Island shoreline warmth. No copyrighted logos."
        )
    return (
        f'Print-ready t-shirt graphic on a {primary} background. Bold headline text "{handle}" paired '
        "with a single illustrated motif. 2-color flat screenprint, generous negative space."
    )


def _brand_tags(brand: Brand, lane: str, handle: str) -> List[str]:
    base = [brand.slug.replace("_", " "), lane.replace("_", " "), slugify(handle)]
    if brand.slug == "earl_biggers":
        base += ["adult humor", "edgy shirt"]
    if brand.slug == "nickle_ts":
        base += ["rhode island", "ri", "tavern", "comfort food", "neighborhood"]
    return base[:10]


def _safety_for(brand: Brand, lane: str) -> List[str]:
    notes: List[str] = ["Avoid copyrighted brands or characters.", "Avoid targeted harassment."]
    if brand.adult_listing_default or lane.lower() in {"force_multipliers", "force-multipliers", "bg_am"}:
        notes.append("Likely needs adult-listing flag on Etsy.")
    return notes


# ---------------- Public surface ----------------
def generate_concept(brand: Brand, handle: str, lane: str, use_api: bool = False) -> Concept:
    """Build a Concept for a brand+lane+handle. Falls back to template if XAI unavailable.

    Always passes the resulting design_prompt through prompt_craft.enhance_design_prompt
    so the anti-hallucination Avoid clause is appended automatically (skill: image_craft).
    """
    from . import prompt_craft

    lane_key = lane.lower().replace("-", "_")
    payload: Optional[Dict[str, Any]] = None
    source = "template"
    if use_api:
        client = XAIClient()
        payload = client.generate(brand, handle, lane_key)
        if payload:
            source = "xai"
    if payload is None:
        payload = template_concept(brand, handle, lane_key)
    title = str(payload["product_title"])
    # Pick subject hint: typography-only for force_multipliers (l33t/code), else
    # cartoon_mascot for earl_biggers (mascot-driven) and nickle_ts (illustrative).
    subject = "typography_only" if lane_key in {"force_multipliers", "force-multipliers"} else "cartoon_mascot"
    enhanced_prompt = prompt_craft.enhance_design_prompt(
        str(payload["design_prompt"]), subject=subject,
    )
    return Concept(
        brand=brand.slug,
        lane=lane_key,
        slug=slugify(f"{brand.slug}-{lane_key}-{title}"),
        input_handle=handle,
        product_title=title,
        tagline=str(payload["tagline"]),
        design_prompt=enhanced_prompt,
        suggested_colors=list(payload.get("suggested_colors") or []),
        tags=list(payload.get("tags") or []),
        safety_notes=list(payload.get("safety_notes") or []),
        source=source,
        extra={},
    )
