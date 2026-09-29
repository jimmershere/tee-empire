#!/usr/bin/env python3
"""Create a Printify DRAFT for a single-design physical product and pull its mockups.

Brand-scoped (reads ``brands/<slug>/brand.yaml`` for the shop id) and deliberately
narrow: sticker / mug / bottle style blueprints that carry one design across a
size or capacity axis. Unlike ``publish_merch_single.py`` this script is not tied
to the Madd Hatchery storefront, never shells out to ``rembg``, and stops at the
draft — it downloads Printify's rendered mockups and exits.

**It never calls ``publish_product``.** ``create_product`` sets ``visible: False``,
so the result is a Printify draft only; pushing it to a connected Etsy shop stays
a human action. See ../CLAUDE.md principle 5.

Usage:
  python3 scripts/publish_merch_draft.py --brand earl_biggers --product bottle \
      --design data/art/au2-logo-fun.png --name "Appearance Unlimited Bottle" \
      --price 28 --slug au2-bottle
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import printify as P  # noqa: E402

# Blueprints that hold one design across a size/capacity axis. Verified against
# Printify's public catalog (GET /v1/catalog/blueprints.json):
#   887 Stainless Steel Water Bottle, Standard Lid
#   478 Ceramic Mug, (11oz, 15oz)
#   400 Kiss-Cut Stickers
#   6   Gildan 5000 Unisex Heavy Cotton Tee
#   77  Gildan 18500 Unisex Heavy Blend Hooded Sweatshirt
BLUEPRINT = {"bottle": 887, "mug": 478, "sticker": 400, "tee": 6, "hoodie": 77}

# Default print provider per product — chosen because it stocks the full AU2
# colourway (black / white / grey / light blue / navy / pink). Override with
# --provider; a provider that lacks a requested colour simply yields fewer
# variants, so --colors reports what it actually matched.
PROVIDER = {"tee": 6, "hoodie": 29}

# Fraction of the print area the art fills. Printify scales relative to print-area
# WIDTH, so the right number depends on the area's aspect vs the art's:
#   tee    front 4500x5700 (0.79, portrait) — portrait art fits happily; the
#          binding limit here is resolution, not geometry (see the DPI note below).
#   hoodie front 3709x2472 (1.50, LANDSCAPE — the band above the kangaroo pocket).
#          Portrait art at 0.9 would overflow the height badly. 0.55 is the
#          largest that fits ~0.83-aspect art, and reads as a normal chest print.
#          For a full-size design the hoodie BACK (3461x3955, 0.88) is the better
#          home — pass --position back --scale 0.9.
# Wrap-around drinkware needs headroom so the design doesn't run into the seam.
SCALE = {"bottle": 0.60, "mug": 0.70, "sticker": 0.95, "tee": 0.60, "hoodie": 0.55}

# Why tee is 0.60 and not 0.90: Printify print areas are sized for 300 DPI, so the
# tee front (4500x5700) is a 15"x19" canvas. The AU2 designs are ~1200 px wide, so
# a 0.90 scale = a 13.5" print upscaled from 1200 px — about 89 DPI, visibly soft.
# 0.60 gives a 9" chest print at ~133 DPI, which holds up for bold cartoon line
# art. To print full-size, re-export the art at 3600 px+ and raise this.


def load_env(path: Path) -> None:
    """Best-effort .env loader. Missing file is not an error (unlike sibling scripts)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.split("#", 1)[0].strip())


def brand_shop_id(brand: str) -> str | None:
    f = ROOT / "brands" / brand / "brand.yaml"
    if not f.exists():
        return None
    try:
        import yaml
        return (yaml.safe_load(f.read_text()) or {}).get("printify_shop_id")
    except Exception:
        return None


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "tee-empire/1.0", "Accept": "image/*"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def download(url: str, dest: Path) -> int:
    data = fetch_bytes(url)
    dest.write_bytes(data)
    return len(data)


def mockup_digest(images: List[Dict[str, Any]]) -> Optional[str]:
    """SHA-256 of the default mockup's *bytes*.

    Printify re-renders a changed draft behind the **same** ``src`` URL — verified:
    two renders of this product at different scales returned an identical URL and
    different image bytes. So a URL comparison can never detect a re-render, and
    the content has to be hashed instead.
    """
    src = next((i.get("src") for i in images if i.get("is_default")), None)
    if not src:
        return None
    try:
        return hashlib.sha256(fetch_bytes(src)).hexdigest()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brand", default="earl_biggers")
    ap.add_argument("--product", required=True, choices=list(BLUEPRINT))
    ap.add_argument("--design", required=True, help="print art (PNG, transparent background)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--slug", required=True, help="used for the mockup folder + upload filename")
    ap.add_argument("--description", default="")
    ap.add_argument("--price", type=float, required=True, help="retail price in USD")
    ap.add_argument("--tags", default="", help="comma-separated")
    ap.add_argument("--scale", type=float, default=None, help="override print scale")
    ap.add_argument("--provider", type=int, default=None,
                    help="print provider id (default: PROVIDER map, else first)")
    ap.add_argument("--colors", default="",
                    help="comma-separated colour names to enable (default: every colour). "
                         "Matched case-insensitively, exact name first then substring.")
    ap.add_argument("--position", default="front",
                    help="print placeholder: front, back, left_sleeve, … (default: front)")
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "mockups"))
    ap.add_argument("--poll", type=int, default=20, help="max mockup polls (5s apart)")
    ap.add_argument("--update", default="", metavar="PRODUCT_ID",
                    help="re-scale an existing draft in place and re-pull mockups, "
                         "instead of creating a second product")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the intended payload and exit without calling Printify")
    args = ap.parse_args()

    load_env(ROOT / ".env")

    bp = BLUEPRINT[args.product]
    scale = args.scale if args.scale is not None else SCALE[args.product]
    price_cents = int(round(args.price * 100))
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    design = Path(args.design)
    if not design.is_absolute():
        design = ROOT / design
    if not design.exists():
        print(f"error: design not found: {design}", file=sys.stderr)
        return 2
    art = design.read_bytes()

    shop_id = os.getenv("PRINTIFY_SHOP_ID") or brand_shop_id(args.brand)

    print(f"brand      : {args.brand}")
    print(f"product    : {args.product}  (blueprint {bp})")
    print(f"design     : {design}  ({len(art) // 1024} KB)")
    print(f"print scale: {scale}")
    print(f"price      : ${args.price:.2f}  ({price_cents} cents)")
    print(f"shop id    : {shop_id or '(unset)'}")

    if args.dry_run:
        print("\n--- DRY RUN: no Printify calls made ---")
        if args.update:
            # --update issues a PUT that rewrites only the transform; describing
            # a create here would make the preview wrong for the very operation
            # being previewed.
            preview = {
                "endpoint": f"PUT /v1/shops/{shop_id}/products/{args.update}.json",
                "note": "re-scales the existing draft in place; no upload, no create",
                "print_areas": [{
                    "variant_ids": "<every variant already on the product, reused verbatim>",
                    "placeholders": [{"position": "<existing>", "images": [
                        {"id": "<existing image id>", "x": "<existing>", "y": "<existing>",
                         "scale": scale, "angle": "<existing>"}]}],
                }],
                "unchanged": ["title", "description", "tags", "variants", "prices", "visible"],
            }
        else:
            preview = {
                "endpoint": f"POST /v1/shops/{shop_id}/products.json",
                "title": args.name,
                "blueprint_id": bp,
                "print_provider_id": args.provider or "<first available>",
                "variants": "<all variants for blueprint/provider> @ %d cents" % price_cents,
                "print_areas": [{"placeholders": [{"position": "front", "images": [
                    {"id": "<upload id>", "x": 0.5, "y": 0.5, "scale": scale, "angle": 0}]}]}],
                "tags": tags,
                "visible": False,
            }
        print(json.dumps(preview, indent=2))
        return 0

    client = P.PrintifyClient(shop_id=shop_id)
    if not client.api_key:
        print("\nerror: PRINTIFY_API_KEY is not set. Add it to /app/tee-empire/.env",
              file=sys.stderr)
        return 3
    if not client.shop_id:
        print("\nerror: no shop id (set PRINTIFY_SHOP_ID or printify_shop_id in brand.yaml)",
              file=sys.stderr)
        return 3

    stale_digest = None
    if args.update:
        # Re-scale an existing draft in place. Printify rejects a print_areas
        # update unless every variant is present, so reuse the product's own
        # print_areas wholesale and only change the transform (error 8251).
        product_id = args.update
        existing = client.get_product(product_id)
        pid = existing.get("print_provider_id")
        vids = [v["id"] for v in existing.get("variants", [])]
        image_id = None
        new_areas = []
        for area in existing.get("print_areas", []):
            phs = []
            for ph in area.get("placeholders", []):
                imgs = []
                for im in ph.get("images", []):
                    image_id = image_id or im.get("id")
                    imgs.append({"id": im["id"], "x": im.get("x", 0.5),
                                 "y": im.get("y", 0.5), "scale": scale,
                                 "angle": im.get("angle", 0)})
                # Apparel carries placeholders it has no art for (a tee has both
                # front and back). Printify rejects an empty `images` array
                # (error 8150), so an unused placeholder is dropped rather than
                # echoed back. Drinkware has a single placeholder, which is why
                # this only shows up on garments.
                if imgs:
                    phs.append({"position": ph.get("position", "front"), "images": imgs})
            if phs:
                new_areas.append({"variant_ids": area.get("variant_ids", []), "placeholders": phs})
        stale_digest = mockup_digest(existing.get("images") or [])
        client.update_product(product_id, {"print_areas": new_areas})
        print(f"\nUPDATED    : draft {product_id} re-scaled to {scale} (still visible=False)")
    else:
        # 1. provider + variants
        prov = client.list_print_providers(bp)
        plist = prov if isinstance(prov, list) else prov.get("data", prov)
        pid = args.provider or PROVIDER.get(args.product) or plist[0]["id"]
        pname = next((p.get("title") for p in plist if p["id"] == pid), "?")
        vres = client.list_variants(bp, pid)
        vlist = vres.get("variants") if isinstance(vres, dict) else vres
        print(f"\nprovider   : {pid} ({pname})")

        if args.colors:
            wanted = [c.strip().lower() for c in args.colors.split(",") if c.strip()]
            available = sorted({v.get("options", {}).get("color", "") for v in vlist
                                if v.get("options", {}).get("color")})
            chosen, missing = [], []
            for w in wanted:
                # Exact name wins; fall back to substring so "grey" finds
                # "Sport Grey" without also dragging in unrelated colourways.
                hit = [c for c in available if c.lower() == w] or \
                      [c for c in available if w in c.lower()]
                if hit:
                    chosen.append(hit[0])
                else:
                    missing.append(w)
            keep = {c.lower() for c in chosen}
            vlist = [v for v in vlist
                     if v.get("options", {}).get("color", "").lower() in keep]
            print(f"colors     : {len(chosen)}/{len(wanted)} matched -> {chosen}")
            if missing:
                # Loud, because a silently-dropped colour is a silently smaller
                # product than the one that was asked for.
                print(f"  WARNING: not stocked by provider {pid}: {missing}", file=sys.stderr)
            if not vlist:
                print("error: no variants matched the requested colors", file=sys.stderr)
                return 5

        vids = [v["id"] for v in vlist]
        sizes_seen = sorted({v.get("options", {}).get("size", "") for v in vlist})
        print(f"variants   : {len(vids)}  ({len(sizes_seen)} sizes: {', '.join(s for s in sizes_seen if s)})")

        # 2. upload print art
        up = client.upload_image(f"{args.slug}-print.png", art)
        image_id = up["id"]
        print(f"uploaded   : image id {image_id}")

        # 3. create the DRAFT (visible: False)
        res = client.create_product(
            title=args.name, description=args.description or args.name,
            blueprint_id=bp, variant_ids=vids, image_id=image_id,
            print_provider_id=pid, tags=tags, price_cents=price_cents,
            product_type=args.product, image_transform={"x": 0.5, "y": 0.5, "scale": scale},
            # `placements` carries the position through; without it create_product
            # hardcodes "front", which silently ignores --position back.
            placements=[{"position": args.position, "image_id": image_id,
                         "x": 0.5, "y": 0.5, "scale": scale, "angle": 0}],
        )
        product_id = res["id"]
        print(f"DRAFT      : printify product {product_id}  (visible=False, not published)")

    # 4. poll until Printify renders the mockups
    # On an --update the old mockups stay attached, at the same URL, until
    # Printify re-renders — so freshness is confirmed by hashing the bytes.
    images: List[Dict[str, Any]] = []
    fresh = False
    for attempt in range(args.poll):
        full = client.get_product(product_id)
        images = full.get("images") or []
        if images:
            if not args.update:               # create path: any render is new
                fresh = True
                break
            if stale_digest is None:
                # Update mode, but the pre-update render could not be hashed
                # (no prior mockup, or the fetch failed). There is no baseline
                # to compare against, so say so rather than claiming freshness.
                print("  note: no pre-update baseline to compare — "
                      "mockup freshness cannot be confirmed", file=sys.stderr)
                fresh = True
                break
            if mockup_digest(images) != stale_digest:
                fresh = True
                break
        print(f"  waiting for mockups... ({attempt + 1}/{args.poll})")
        time.sleep(5)

    if not images:
        print("warning: no mockups rendered yet; re-run get_product later", file=sys.stderr)
    elif not fresh:
        # The old render is still being served. Saving it would silently file
        # stale images under the new slug and report them as the new scale.
        print(f"\nERROR: Printify had not re-rendered after {args.poll * 5}s — the mockups "
              f"still match the previous render.\n"
              f"       Nothing was downloaded, so the stale images cannot be mistaken for "
              f"the new scale.\n"
              f"       The draft itself IS updated. Re-run the same command with a longer "
              f"--poll to collect mockups.", file=sys.stderr)
        return 4

    # 5. download them
    out = Path(args.out_dir) / args.slug
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, im in enumerate(images):
        src = im.get("src")
        if not src:
            continue
        ext = ".png" if ".png" in src.lower() else ".jpg"
        tag = "default" if im.get("is_default") else (im.get("position") or f"view{i}")
        name = f"{args.slug}-{i:02d}-{tag}{ext}"
        try:
            n = download(src, out / name)
            saved.append({"file": name, "bytes": n, "position": im.get("position"),
                          "is_default": bool(im.get("is_default")),
                          "variant_ids": im.get("variant_ids", []), "src": src})
            print(f"  saved {name}  ({n // 1024} KB)")
        except Exception as e:
            print(f"  FAILED {name}: {e}", file=sys.stderr)

    manifest = {"brand": args.brand, "product": args.product, "blueprint_id": bp,
                "print_provider_id": pid, "printify_product_id": product_id,
                "shop_id": client.shop_id, "image_id": image_id, "name": args.name,
                "price_cents": price_cents, "scale": scale, "visible": False,
                "published": False, "variant_count": len(vids),
                # True only when the bytes were confirmed to differ from the
                # pre-update render, so a manifest never implies a freshness
                # that was not actually observed.
                "mockups_confirmed_fresh": fresh,
                "mockups": saved}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nmockups    : {out}  ({len(saved)} images + manifest.json)")
    print("next       : review the mockups, then publish from the Printify dashboard "
          "(this script never publishes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
