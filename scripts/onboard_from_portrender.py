#!/usr/bin/env python3
"""Onboard a brand into tee-empire straight from its portrender brand file.

The brand facts already exist once, in `/app/portrender/brands/<slug>.toml` — voice,
palette, audience, product list, taglines. Retyping them into an `intake.json` is how
two sources of truth get born. This reads the TOML, writes the intake, and (unless
you pass --intake-only) runs `onboard_brand.py` for you.

    # see what it would write, change nothing
    python3 scripts/onboard_from_portrender.py au2 --dry-run

    # scaffold brands/au2/ + the clemtock theme
    python3 scripts/onboard_from_portrender.py au2

    # every brand portrender knows about
    python3 scripts/onboard_from_portrender.py --all

For a brand-new customer who is NOT in portrender yet, use the intake questionnaire in
ONBOARDING.md §1 and run `scripts/onboard_brand.py intake.json` directly.

Printify shop ids are deliberately left blank unless the TOML carries one: a brand with
no shop still scaffolds and still runs dry-run end to end, which is the right default.
Filling in a shop id you guessed would publish someone else's products into it.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTRENDER_BRANDS = Path("/app/portrender/brands")

_HEX = re.compile(r"#[0-9a-fA-F]{3,8}")


def _hexes(palette: list[str]) -> list[str]:
    """portrender palettes are '#b8121b red' style; pull the hex, keep the order."""
    out = []
    for entry in palette or []:
        m = _HEX.search(str(entry))
        if m:
            out.append(m.group(0))
    return out


def to_intake(toml_path: Path) -> dict:
    d = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    pal = _hexes(d.get("palette", []))
    # onboard_brand.py wants exactly four named slots; pad from what we have rather
    # than inventing colours that are not the brand's.
    slots = ["primary", "secondary", "accent", "cream"]
    palette = {k: (pal[i] if i < len(pal) else (pal[-1] if pal else "#222222"))
               for i, k in enumerate(slots)}

    lanes_in = d.get("lanes", {}) or {}
    lanes = {k: list(v) for k, v in lanes_in.items() if isinstance(v, list)}
    if not lanes:
        lanes = {"house": []}

    mascot = d.get("mascot", {}) or {}
    links = d.get("links", {}) or {}
    handoff = d.get("handoff", {}) or {}

    intake = {
        "slug": d.get("slug") or toml_path.stem,
        "name": d.get("name", toml_path.stem),
        "tagline": d.get("tagline", ""),
        "location": d.get("location", ""),
        "site_url": links.get("site", ""),
        "voice": d.get("voice", ""),
        "palette": palette,
        "products": d.get("products", ["tees"]),
        "niches": d.get("products", ["tees"]),
        "audiences": {"primary": d.get("audience", "")} if d.get("audience") else {},
        "lanes": lanes,
        "commerce": {},
        "_source": str(toml_path),
        "_note": d.get("notes", ""),
    }
    # Only carry a mascot if there is one; "none" is a real answer in these files.
    if mascot.get("name") and mascot["name"].lower() not in ("none", ""):
        intake["mascot"] = {"name": mascot.get("name", ""),
                            "desc": mascot.get("desc", ""),
                            "ref": mascot.get("ref", "")}
    if handoff.get("clemtock_theme"):
        intake["clemtock_theme"] = handoff["clemtock_theme"]
    return intake


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*", help="brand slugs (portrender/brands/<slug>.toml)")
    ap.add_argument("--all", action="store_true", help="every .toml portrender has")
    ap.add_argument("--dry-run", action="store_true", help="print the intake, write nothing")
    ap.add_argument("--intake-only", action="store_true",
                    help="write intake.json but do not run onboard_brand.py")
    ap.add_argument("--brands-dir", default=str(PORTRENDER_BRANDS))
    args = ap.parse_args()

    brands_dir = Path(args.brands_dir)
    if not brands_dir.is_dir():
        print(f"portrender brands not found: {brands_dir}", file=sys.stderr)
        return 2

    slugs = args.slugs
    if args.all:
        slugs = sorted(p.stem for p in brands_dir.glob("*.toml"))
    if not slugs:
        print("give one or more slugs, or --all. Available: "
              + ", ".join(sorted(p.stem for p in brands_dir.glob("*.toml"))), file=sys.stderr)
        return 2

    rc = 0
    for slug in slugs:
        toml_path = brands_dir / f"{slug}.toml"
        if not toml_path.is_file():
            print(f"!! no such brand file: {toml_path}", file=sys.stderr)
            rc = 1
            continue
        intake = to_intake(toml_path)

        if args.dry_run:
            print(f"--- {slug} ---")
            print(json.dumps(intake, indent=2))
            continue

        out_dir = ROOT / "brands" / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        intake_path = out_dir / "intake.json"
        intake_path.write_text(json.dumps(intake, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {intake_path}")

        if args.intake_only:
            continue
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / "onboard_brand.py"),
                              str(intake_path)], cwd=ROOT)
        if res.returncode != 0:
            print(f"!! onboard_brand.py failed for {slug}", file=sys.stderr)
            rc = res.returncode
        else:
            print(f"onboarded {slug} -> brands/{slug}/brand.yaml")
            if not intake.get("commerce", {}).get("printify_shop_id"):
                print(f"   note: no printify_shop_id — {slug} runs dry-run until you add one")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
