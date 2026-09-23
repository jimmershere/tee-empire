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
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import printify as P  # noqa: E402

# Blueprints that hold one design across a size/capacity axis. Verified against
# Printify's public catalog (GET /v1/catalog/blueprints.json):
#   887 Stainless Steel Water Bottle, Standard Lid
#   478 Ceramic Mug, (11oz, 15oz)
#   400 Kiss-Cut Stickers
BLUEPRINT = {"bottle": 887, "mug": 478, "sticker": 400}

# Fraction of the print area the art fills. Wrap-around products need headroom so
# the design doesn't run into the seam.
SCALE = {"bottle": 0.60, "mug": 0.70, "sticker": 0.95}


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


def download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "tee-empire/1.0", "Accept": "image/*"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    dest.write_bytes(data)
    return len(data)


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
    ap.add_argument("--provider", type=int, default=None, help="print provider id (default: first)")
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "mockups"))
    ap.add_argument("--poll", type=int, default=20, help="max mockup polls (5s apart)")
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
        print(json.dumps({
            "endpoint": f"POST /v1/shops/{shop_id}/products.json",
            "title": args.name,
            "blueprint_id": bp,
            "print_provider_id": args.provider or "<first available>",
            "variants": "<all variants for blueprint/provider> @ %d cents" % price_cents,
            "print_areas": [{"placeholders": [{"position": "front", "images": [
                {"id": "<upload id>", "x": 0.5, "y": 0.5, "scale": scale, "angle": 0}]}]}],
            "tags": tags,
            "visible": False,
        }, indent=2))
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

    # 1. provider + variants
    prov = client.list_print_providers(bp)
    plist = prov if isinstance(prov, list) else prov.get("data", prov)
    pid = args.provider or plist[0]["id"]
    pname = next((p.get("title") for p in plist if p["id"] == pid), "?")
    vres = client.list_variants(bp, pid)
    vlist = vres.get("variants") if isinstance(vres, dict) else vres
    vids = [v["id"] for v in vlist]
    print(f"\nprovider   : {pid} ({pname})")
    print(f"variants   : {len(vids)} -> {[v.get('title') for v in vlist][:6]}")

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
    )
    product_id = res["id"]
    print(f"DRAFT      : printify product {product_id}  (visible=False, not published)")

    # 4. poll until Printify renders the mockups
    images: List[Dict[str, Any]] = []
    for attempt in range(args.poll):
        full = client.get_product(product_id)
        images = full.get("images") or []
        if images:
            break
        print(f"  waiting for mockups... ({attempt + 1}/{args.poll})")
        time.sleep(5)
    if not images:
        print("warning: no mockups rendered yet; re-run get_product later", file=sys.stderr)

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
                "published": False, "variant_count": len(vids), "mockups": saved}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nmockups    : {out}  ({len(saved)} images + manifest.json)")
    print("next       : review the mockups, then publish from the Printify dashboard "
          "(this script never publishes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
