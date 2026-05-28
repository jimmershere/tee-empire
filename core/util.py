"""Empire shared utilities."""
from __future__ import annotations

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


def sanitize_for_marketplace(text: str) -> str:
    """Normalize Unicode sub/superscripts and other glyphs that Printify/Etsy reject.

    Subscript digits (`C₅H₁₀O₃N`) → ASCII digits (`C5H10O3N`).
    Superscript digits (`x²`) → ASCII digits (`x2`).
    Other Unicode is left alone — marketplaces handle most things; it's specifically
    sub/superscript codepoints that have been known to break Printify's product API.
    """
    if not text:
        return text
    return text.translate(_SUBSCRIPT_TR).translate(_SUPERSCRIPT_TR)
