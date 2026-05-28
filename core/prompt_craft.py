"""Anti-hallucination + prompt-craft helpers for empire's image generation.

Implements the rules in `empire/skills/image_craft/`. Two entry points:

1. ``avoid_clause(subject)`` — returns the appropriate "Avoid: ..." string for
   a given subject type. Folds the anti-hallucination vocabulary directly into
   the positive prompt (since nano-banana-2 / GPT-Image-2 / cloud backends
   honour it; ComfyUI's negative-prompt node is handled separately).

2. ``enhance_design_prompt(prompt, subject)`` — ensures a design prompt
   follows the canonical shape (canvas → subject → style → composition →
   headline → avoid) and appends the avoid clause if absent.

Sourced from `https://github.com/jimmershere/exec_dashbd` skill bundle.
"""
from __future__ import annotations

import re
from typing import Iterable, Literal, Optional

Subject = Literal["cartoon_mascot", "humanoid", "animal", "typography_only", "none"]


# Anatomy / anti-hallucination vocabulary, curated per subject type.
# Source: skills/image_craft/anatomy_avoid.md
_AVOID_VOCAB: dict[str, list[str]] = {
    "cartoon_mascot": [
        "extra limbs", "missing limbs", "fused limbs",
        "extra arms", "extra legs", "missing arms", "missing legs",
        "three legs", "six fingers", "fused fingers",
        "mutated hand", "malformed face", "mirrored face",
        "doubled face", "two heads", "off-model anatomy",
        "broken silhouette", "floating limb", "disconnected limb",
        "extra characters", "duplicate of the subject",
        "cluttered background", "busy negative space",
    ],
    "humanoid": [
        "extra fingers", "six fingers", "fused fingers",
        "mutated hand", "poorly drawn hand", "twisted finger",
        "missing thumb", "extra elbow", "extra knee",
        "three legs", "missing limb", "floating limb",
        "disconnected limb", "malformed limb", "bad anatomy",
        "gross proportions", "long neck", "mirrored face",
        "doubled face", "cloned face", "two heads",
        "distorted face", "asymmetric eyes", "deformed mouth",
    ],
    "animal": [
        "wrong number of legs", "three legs", "five legs",
        "missing leg", "extra leg", "extra tail", "two tails",
        "missing tail", "missing ear", "three ears", "fused ears",
        "extra eye", "three eyes", "missing eye", "mirrored eyes",
        "asymmetric face", "deformed paw", "malformed snout",
        "broken silhouette", "off-model anatomy",
    ],
    "typography_only": [
        "no people", "no faces", "no hands", "no body parts",
        "no animals", "no characters", "no random objects",
        "no clutter in negative space", "garbled text",
        "duplicated text", "misspelled headline",
        "extra characters in the text",
    ],
}

# Universal — always append regardless of subject type.
_UNIVERSAL_AVOID: list[str] = [
    "watermark", "signature", "artist mark", "copyright mark",
    "brand logo not requested", "caption text outside the headline",
    "QR code", "stock-photo overlay",
    "jpeg compression artifacts", "ringing", "blurry edges",
]


def avoid_clause(subject: Subject = "cartoon_mascot",
                 extra: Optional[Iterable[str]] = None) -> str:
    """Build the ``Avoid: ...`` clause for a positive prompt.

    Returns the full clause including the leading ``Avoid: `` prefix. Empty
    string when ``subject="none"`` and no extras provided.
    """
    items: list[str] = []
    if subject != "none":
        items.extend(_AVOID_VOCAB.get(subject, []))
    items.extend(_UNIVERSAL_AVOID)
    if extra:
        items.extend(list(extra))
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return "Avoid: " + ", ".join(unique) + "."


def _classify_subject(prompt: str) -> Subject:
    """Heuristic classification of a design prompt by what's in it.

    Looks for keywords identifying mascot/character/animal/typography-only.
    Defaults to ``cartoon_mascot`` because that's earl_biggers' bread and butter.
    """
    p = prompt.lower()
    # Typography-only: no character/mascot words AND mentions only-text style.
    character_words = ("skeleton", "mascot", "character", "person", "figure",
                       "creature", "monster", "ghost", "cartoon character")
    animal_words = ("animal", "cat", "dog", "bear", "wolf", "fox", "rabbit",
                    "bird", "fish", "quadruped", "snake", "horse")
    typography_signals = ("typography only", "no illustration", "minimal typography",
                          "text-only", "type-only", "no mascot")
    if any(w in p for w in typography_signals):
        return "typography_only"
    if any(w in p for w in animal_words):
        return "animal"
    if any(w in p for w in character_words):
        return "cartoon_mascot"
    # Default: assume there's a mascot — empire's bread and butter.
    return "cartoon_mascot"


def has_avoid_clause(prompt: str) -> bool:
    return bool(re.search(r"\b[Aa]void\s*:", prompt))


def enhance_design_prompt(prompt: str, *, subject: Optional[Subject] = None,
                          extra_avoid: Optional[Iterable[str]] = None,
                          force: bool = False) -> str:
    """Return a design prompt with the Avoid clause appended (if missing).

    If ``subject`` is ``None``, infers it from the prompt content. If the
    prompt already contains an ``Avoid:`` clause, returns it unchanged
    unless ``force=True``.
    """
    if not force and has_avoid_clause(prompt):
        return prompt
    if subject is None:
        subject = _classify_subject(prompt)
    if subject == "none":
        return prompt
    clause = avoid_clause(subject, extra=extra_avoid)
    sep = " " if not prompt.endswith((" ", "\n")) else ""
    return f"{prompt.rstrip()}{sep} {clause}"
