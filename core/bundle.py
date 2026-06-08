"""Default merch bundle definition for the drop-folder pipeline.

One dropped image and/or prompt fans out into this fixed set of Printify
drafts. All blueprint / print-provider / variant IDs below were copied from
existing *live* products on shop 27415408 (which already sync to Etsy), so they
are known-good for this account.

Tee colors: black, navy, light blue, red, orange, yellow (Maize), grey
(Athletic Heather). Tie-dye is intentionally absent: Bella+Canvas 3001
(blueprint 12) is not offered in tie-dye by any Printify DTG provider, so it
cannot be a color *variant* on the same listing. See TIE_DYE_NOTE.
"""
from __future__ import annotations

from typing import Dict, List

TIE_DYE_NOTE = (
    "Tie-dye is not available on Bella+Canvas 3001 (the tee blueprint used here) "
    "from any Printify print provider, so it can't be added as a color variant on "
    "this listing. To offer tie-dye you'd need a separate tie-dye garment blueprint "
    "as its own listing."
)

# Tee blueprint 12 / provider 99 (Printify Choice), 7 colors x all available sizes.
TEE_VARIANT_IDS: List[int] = [
    # Black  (XS,S,M,L,XL,2XL,3XL,4XL,5XL)
    18099, 18100, 18101, 18102, 18103, 18104, 18105, 18106, 101666,
    # Navy
    18395, 18396, 18397, 18398, 18399, 18400, 18401, 18402, 101747,
    # Light Blue (no 5XL)
    18355, 18356, 18357, 18358, 18359, 18360, 18361, 18362,
    # Red
    18443, 18444, 18445, 18446, 18447, 18448, 18449, 18450, 101756,
    # Orange (no 5XL)
    18419, 18420, 18421, 18422, 18423, 18424, 18425, 18426,
    # Maize Yellow (no 5XL)
    18363, 18364, 18365, 18366, 18367, 18368, 18369, 18370,
    # Athletic Heather / grey (no 5XL)
    18075, 18076, 18077, 18078, 18079, 18080, 18081, 18082,
]

TEE_COLOR_LABELS = ["Black", "Navy", "Light Blue", "Red", "Orange", "Maize Yellow", "Athletic Heather"]

# Per-color variant groupings (used to reduce a back-text tee to a single
# colorway). Printify only renders back/model/folded mockups for single-color
# tee listings; a multi-color listing gets one front per color and no back. So
# when text is stamped on the BACK we shrink the listing to TWO_SIDED_COLORS to
# get the full mockup set, which then syncs to Etsy for free.
TEE_COLOR_VARIANTS: Dict[str, List[int]] = {
    "Black":             [18099, 18100, 18101, 18102, 18103, 18104, 18105, 18106, 101666],
    "Navy":              [18395, 18396, 18397, 18398, 18399, 18400, 18401, 18402, 101747],
    "Light Blue":        [18355, 18356, 18357, 18358, 18359, 18360, 18361, 18362],
    "Red":               [18443, 18444, 18445, 18446, 18447, 18448, 18449, 18450, 101756],
    "Orange":            [18419, 18420, 18421, 18422, 18423, 18424, 18425, 18426],
    "Maize Yellow":      [18363, 18364, 18365, 18366, 18367, 18368, 18369, 18370],
    "Athletic Heather":  [18075, 18076, 18077, 18078, 18079, 18080, 18081, 18082],
}

# Colorway(s) kept when a tee gets back text. Single color matches the proven
# pattern (every shop product with a back mockup is single-color); add a 2nd
# label here if testing confirms 2 colors still renders the back.
TWO_SIDED_COLORS = ["Black"]

# Tie-dye tee: blueprint 1950 (Gildan Unisex Tie Dye Cotton Tee) / provider 29
# (Monster Digital). Multi-color tie-dye colorways: Neon Rainbow, Tropical Dream,
# Summer Sky, Powder Clouds. Sizes M/L/XL/2XL (varies by colorway). This is a
# SEPARATE listing from the standard tee — tie-dye can't be a color variant on
# Bella+Canvas 3001 (see TIE_DYE_NOTE).
TIEDYE_VARIANT_IDS: List[int] = [
    120856, 120857,                  # 2XL: Summer Sky, Tropical Dream
    120860, 120861, 120862,          # L:   Powder Clouds, Summer Sky, Tropical Dream
    120864, 120865, 120866, 120867,  # M:   Neon Rainbow, Powder Clouds, Summer Sky, Tropical Dream
    120870, 120871, 120872,          # XL:  Powder Clouds, Summer Sky, Tropical Dream
]
TIEDYE_COLOR_LABELS = ["Neon Rainbow", "Tropical Dream", "Summer Sky", "Powder Clouds"]

TIEDYE_COLOR_VARIANTS: Dict[str, List[int]] = {
    "Neon Rainbow":   [120864],
    "Tropical Dream": [120857, 120862, 120867, 120872],
    "Summer Sky":     [120856, 120861, 120866, 120871],
    "Powder Clouds":  [120860, 120865, 120870],
}

# Summer Sky has the most complete size run (M/L/XL/2XL), so it's the default
# single colorway kept when a tie-dye tee gets back text.
TIEDYE_TWO_SIDED_COLORS = ["Summer Sky"]

# Each product becomes one Printify draft + one approval card.
# mockup: which local compositor to use (shirt/mug/sticker/poster).
# price_cents are sensible starting points — edit per taste.
BUNDLE: List[Dict] = [
    {
        "key": "tee",
        "label": "Tee · 7 colors",
        "title_suffix": "Tee",
        "blueprint_id": 12,
        "print_provider_id": 99,
        "variant_ids": TEE_VARIANT_IDS,
        "price_cents": 2600,
        "mockup": "shirt",
        "description": (
            "Made-to-order soft tee — Bella+Canvas 3001 unisex jersey. "
            "Available in Black, Navy, Light Blue, Red, Orange, Yellow and Grey, "
            "sizes XS-5XL (varies by color). Ships fast."
        ),
    },
    {
        "key": "tiedye",
        "label": "Tie-Dye Tee · multi-color",
        "title_suffix": "Tie-Dye Tee",
        "blueprint_id": 1950,
        "print_provider_id": 29,
        "variant_ids": TIEDYE_VARIANT_IDS,
        "price_cents": 3200,
        "mockup": "shirt",
        "description": (
            "Made-to-order multi-color tie-dye tee — Gildan heavy cotton, "
            "hand-dyed swirl. Colorways: Neon Rainbow, Tropical Dream, Summer Sky, "
            "Powder Clouds. Sizes M-2XL (varies by colorway). Every piece is unique."
        ),
    },
    {
        "key": "mug",
        "label": "15oz Mug",
        "title_suffix": "15oz Coffee Mug",
        "blueprint_id": 425,
        "print_provider_id": 1,
        "variant_ids": [62014],
        "price_cents": 1800,
        "mockup": "mug",
        "description": "15oz ceramic mug. Dishwasher & microwave safe. Made-to-order.",
        # The 15oz front print area is 2790x1219 (wide). At full scale a square
        # logo overflows and crops; shrink it into the top ~90% and lift it so
        # the bottom ~10% stays clear for an underneath text line.
        "image_transform": {"x": 0.5, "y": 0.45, "scale": 0.39},
    },
    {
        "key": "sticker",
        "label": '4" Sticker',
        "title_suffix": "4 Inch Sticker",
        "blueprint_id": 400,
        "print_provider_id": 99,
        "variant_ids": [45752],
        "price_cents": 500,
        "mockup": "sticker",
        "description": 'High-quality 4" x 4" vinyl sticker. Weather & scratch resistant. Made-to-order.',
    },
    {
        "key": "poster",
        "label": "Poster · 11x14",
        "title_suffix": "Poster",
        "blueprint_id": 97,
        "print_provider_id": 99,
        "variant_ids": [33749],  # 11" x 14"
        "price_cents": 1500,
        "mockup": "poster",
        "description": "Museum-quality 11\" x 14\" poster on thick matte paper. Made-to-order.",
    },
]


def product_spec(key: str) -> Dict:
    for p in BUNDLE:
        if p["key"] == key:
            return p
    raise KeyError(f"unknown bundle product: {key}")


def _two_sided_config(key: str):
    """(color labels, color->variants table) used to shrink a back-text tee."""
    if key == "tiedye":
        return TIEDYE_TWO_SIDED_COLORS, TIEDYE_COLOR_VARIANTS
    return TWO_SIDED_COLORS, TEE_COLOR_VARIANTS


def two_sided_color_labels(key: str) -> List[str]:
    return list(_two_sided_config(key)[0])


def two_sided_variant_ids(key: str) -> List[int]:
    """Variant IDs to keep enabled when this product gets back text."""
    colors, table = _two_sided_config(key)
    ids: List[int] = []
    for c in colors:
        ids.extend(table.get(c, []))
    return ids
