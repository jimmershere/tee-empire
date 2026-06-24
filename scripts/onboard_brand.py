#!/usr/bin/env python3
"""Onboard a new customer/brand from an intake.json (see ONBOARDING.md).

Scaffolds, idempotently:
  brands/<slug>/brand.yaml
  brands/<slug>/lanes/<lane>.json
  brands/<slug>/fixtures/            (drop logo.png + character.png here)
  <clemtock>/themes/<slug>.json      (ad theme + prompt presets)

Usage:  python scripts/onboard_brand.py intake.json [--clemtock ../clemtock]
"""
from __future__ import annotations
import argparse, json, re, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(s).lower())).strip("-")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("intake")
    ap.add_argument("--clemtock", default=str(ROOT.parent / "clemtock"))
    args = ap.parse_args()

    data = json.loads(Path(args.intake).read_text())
    slug = slugify(data.get("slug") or data["name"])
    pal = data.get("palette", {})
    primary = pal.get("primary", "#119aa0"); secondary = pal.get("secondary", "#7a3f9d")
    accent = pal.get("accent", "#e0922f"); cream = pal.get("cream", "#f6eedb")
    lanes = data.get("lanes") or {"house": [], "novelty": []}
    products = data.get("products", ["tees"])

    bdir = ROOT / "brands" / slug
    (bdir / "lanes").mkdir(parents=True, exist_ok=True)
    (bdir / "fixtures").mkdir(parents=True, exist_ok=True)

    # brand.yaml
    yaml = [
        f"slug: {slug}",
        f"name: {data.get('name', slug)}",
        f"voice: >-\n  {data.get('voice','friendly, down-home brand voice')}",
        "niches:",
        *[f"  - {n}" for n in data.get("niches", products)],
        "palette:",
        *[f"  - \"{c}\"" for c in (primary, secondary, accent, cream)],
        "lanes:",
        *[f"  - {slugify(l)}" for l in lanes.keys()],
        "adult_listing_default: false",
        "pricing:",
        f"  base_usd: {float(data.get('pricing', {}).get('base_usd', 28.0))}",
        f"printify_shop_id: \"{data.get('commerce', {}).get('printify_shop_id', '') or ''}\"",
        "printify_blueprint_id: 12",
        "printify_print_provider_id: 6",
        "printify_variant_ids: [18100, 18101, 18102, 18103, 18104]",
        f"printify_price_cents: {int(float(data.get('pricing', {}).get('base_usd', 28.0)) * 100)}",
        "etsy_shop_id: null",
        "review_chat_id: null",
    ]
    (bdir / "brand.yaml").write_text("\n".join(yaml) + "\n")

    # lanes
    for lane, seeds in lanes.items():
        (bdir / "lanes" / f"{slugify(lane)}.json").write_text(
            json.dumps({"lane": slugify(lane), "seeds": seeds or []}, indent=2) + "\n")

    # copy logo / mascot if provided
    for key, dst in (("logo", "logo.png"), ("mascot_ref", "character.png")):
        src = data.get(key) or (data.get("mascot", {}) or {}).get("ref") if key == "mascot_ref" else data.get("logo")
        if src and Path(src).exists():
            shutil.copy(src, bdir / "fixtures" / dst)

    # clemtock theme
    mascot = data.get("mascot", {}) or {}
    theme = {
        "name": slug, "label": data.get("name", slug),
        "ref": data.get("site_url", ""),
        "location": data.get("location", ""),
        "palette": {"ink": secondary, "cream": cream, "text": cream, "muted": "#cbe0db",
                    "lime": primary, "orange": accent, "line": "#234a52", "line2": "#2c5a62"},
        "style_prompt": f"Bold vintage cartoon sticker style, thick outlines, bright flat colors. "
                        f"Palette: {primary}, {secondary}, {cream}, {accent}. {data.get('voice','')} No text.",
        "backdrop_prompt": f"Soft blurred vertical brand background in {primary}/{secondary} tones with "
                           f"subtle motifs, warm glow, vignette, muted, no text. {data.get('name','')} look.",
        "mascots": {mascot.get("name", "mascot").lower(): mascot.get("desc", "")} if mascot else {},
        "audiences": data.get("audiences", {}),
        "qr_target": data.get("commerce", {}).get("qr_target", data.get("site_url", "")),
    }
    clem = Path(args.clemtock)
    (clem / "themes").mkdir(parents=True, exist_ok=True)
    (clem / "themes" / f"{slug}.json").write_text(json.dumps(theme, indent=2) + "\n")

    print(f"✅ onboarded '{slug}'")
    print(f"   brand:  {bdir}/brand.yaml  (+ {len(lanes)} lanes, fixtures/)")
    print(f"   theme:  {clem}/themes/{slug}.json")
    print("   next: drop logo.png + character.png into fixtures/, then")
    print(f"         python -m empire plan --brand {slug} --per-lane 5")
    print(f"         python -m empire design --brand {slug} --product-type shirt --live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
