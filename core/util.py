"""Empire shared utilities."""
from __future__ import annotations

import re

# Unicode subscript/superscript → ASCII mapping for marketplace-facing text.
# Printify (and to a lesser extent Etsy) refuses or mangles many non-ASCII
# characters in titles/tags. We preserve the original on the *design itself*
# (the buyer sees the Unicode rendered by the image model) but convert to ASCII
# for the listing title/description/tags.
_SUBSCRIPT_TR = str.maketrans(
    "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ",
    "0123456789+-=()aehijklmnoprstuvx",
)
_SUPERSCRIPT_TR = str.maketrans(
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ",
    "0123456789+-=()abcdefghijklmnoprstuvwxyz",
)


# Profanity vowel-censor — replaces the middle vowel of a few words with `*`
# so marketplace titles stay search-friendly while the design itself keeps
# whatever language was intended. `brainfuck` → `brainf*ck`. Substring match
# is intentional: catches compound words ("brainfuck", "fucked", "fucker").
# Format: (compiled regex, 0-indexed vowel position within the match).
_PROFANITY_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"f[uU]ck", re.IGNORECASE), 1),   # fuck → f*ck
    (re.compile(r"sh[iI]t", re.IGNORECASE), 2),   # shit → sh*t
    (re.compile(r"sh[iI]tt(?=[a-zA-Z])", re.IGNORECASE), 2),  # shitting → sh*tting
]


def censor_profanity(text: str) -> str:
    """Soft-censor a small profanity set by swapping the vowel for `*`.

    Case-preserving. Idempotent — re-running on already-censored text is a no-op
    because the patterns require a literal vowel where the asterisk now sits.
    """
    if not text:
        return text
    out = text
    for pat, vowel_idx in _PROFANITY_PATTERNS:
        def _repl(m: re.Match[str], idx: int = vowel_idx) -> str:
            s = m.group(0)
            return s[:idx] + "*" + s[idx + 1:]
        out = pat.sub(_repl, out)
    return out


def sanitize_for_marketplace(text: str) -> str:
    """Normalize text before pushing to Printify/Etsy.

    Two passes:
      1. Subscript/superscript Unicode → ASCII (`C₅H₁₀O₃N` → `C5H10O3N`,
         `x²` → `x2`). Printify in particular has been known to reject these.
      2. Profanity vowel-censor (`brainfuck` → `brainf*ck`, `fuck` → `f*ck`).
         Keeps the marketplace listing search-friendly while preserving the
         original intent on the design itself.
    """
    if not text:
        return text
    text = text.translate(_SUBSCRIPT_TR).translate(_SUPERSCRIPT_TR)
    text = censor_profanity(text)
    return text
