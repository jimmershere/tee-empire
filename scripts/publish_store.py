#!/usr/bin/env python3
"""Publish a design to the Madd Hatchery storefront as a REAL Printify product
with selectable variants (color/size) + real per-color mockup photos.

Flow: create (or reuse) a Printify product on the right blueprint with the
chosen colors x sizes -> fetch Printify's per-color mockups -> color-map them ->
POST product + variants + per-color images to the storefront admin API.

Usage:
  python scripts/publish_store.py --brand madd_hatchery --concept <slug> \
      --product tee --price 28 --slug hatch-different-tee --name "Hatch Different Tee" \
      --category madd-tee --colors "Black,White,Navy,Sand,Sport Grey,Cardinal Red,Forest Green,Royal" \
      --api http://localhost:3310 [--printify-product <id>] [--create]
"""
from __future__ import annotations
import argparse, base64, io, json, os, sys, types, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for n, d in (("empire", "empire"), ("empire.core", "core")):
    m = types.ModuleType(n); m.__path__ = [str(ROOT / d)]; m.__package__ = n; sys.modules[n] = m
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.split("#", 1)[0].strip())

from empire.core import printify as P  # noqa: E402
from PIL import Image  # noqa: E402

BLUEPRINT = {"tee": 6, "tiedye": 632, "mug": 478, "bottle": 887, "sticker": 400}
DEFAULT_SIZES = {"tee": ["S", "M", "L", "XL", "2XL", "3XL", "4XL"], "tiedye": ["S", "M", "L", "XL", "2XL"]}
COLOR_HEX = {  # swatch hexes for common tee colors
    "Black": "#1b1b1b", "White": "#f4f4f2", "Navy": "#1f2a44", "Sand": "#d9c9a3",
    "Sport Grey": "#b4b4b4", "Cardinal Red": "#8a1f2b", "Forest Green": "#21402a",
    "Royal": "#1c3f94", "Maroon": "#5a1a2b", "Gold": "#f0b429", "Light Blue": "#a8c8e8",
}


def http_post(url, payload, token):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Admin-Token": token})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def dl(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
    return urllib.request.urlopen(req, timeout=40).read()


def shirt_rgb(png):
    im = Image.open(io.BytesIO(png)).convert("RGB"); w, h = im.size
    pts = [(int(w * .30), int(h * .74)), (int(w * .70), int(h * .74)), (int(w * .30), int(h * .42)), (int(w * .70), int(h * .42))]
    rs = [im.getpixel(p) for p in pts]
    return tuple(sum(c[i] for c in rs) // len(rs) for i in range(3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True); ap.add_argument("--concept", required=True)
    ap.add_argument("--product", default="tee", choices=list(BLUEPRINT))
    ap.add_argument("--slug", required=True); ap.add_argument("--name", required=True)
    ap.add_argument("--category", required=True); ap.add_argument("--price", type=float, default=28.0)
    ap.add_argument("--colors", default="Black,White,Navy,Sand,Sport Grey,Cardinal Red,Forest Green,Royal")
    ap.add_argument("--sizes", default=""); ap.add_argument("--description", default="")
    ap.add_argument("--api", default=os.getenv("MADDHATCHERY_API_URL", "https://maddhatchery.com"))
    ap.add_argument("--printify-product", default=None)
    ap.add_argument("--logo", default="/app/maddhatch/public/assets/v3/logo_2026.png",
                    help="front-left-chest trademark logo (apparel only)")
    args = ap.parse_args()

    token = os.environ["MADDHATCHERY_ADMIN_TOKEN"]
    price_cents = int(round(args.price * 100))
    bp = BLUEPRINT[args.product]
    want_colors = [c.strip() for c in args.colors.split(",") if c.strip()]
    sizes = [s.strip() for s in args.sizes.split(",") if s.strip()] or DEFAULT_SIZES.get(args.product, ["One Size"])

    c = P.PrintifyClient(shop_id=os.environ.get("PRINTIFY_SHOP_ID"))
    prov = c.list_print_providers(bp); pl = prov if isinstance(prov, list) else prov.get("data", prov)
    # Pick the print provider that carries the most of our wanted colors (provider order isn't stable).
    best = None
    for prv in pl:
        try:
            v2 = c.list_variants(bp, prv["id"]); l2 = v2.get("variants") if isinstance(v2, dict) else v2
            cov = len([c0 for c0 in want_colors if c0 in {x.get("options", {}).get("color") for x in (l2 or [])}])
            if best is None or cov > best[1]: best = (prv["id"], cov, l2)
            if cov >= len(want_colors): break
        except Exception:
            continue
    PID, _, vl = best
    have = {v.get("options", {}).get("color") for v in vl}
    colors = [c0 for c0 in want_colors if c0 in have][:8] or sorted([x for x in have if x])[:8]

    matrix, vids = {}, []
    for v in vl:
        o = v.get("options", {}); col, sz = o.get("color"), o.get("size")
        if col in colors and (sz in sizes or (sz is None and "One Size" in sizes)):
            matrix.setdefault(col, {})[sz or "One Size"] = v["id"]; vids.append(v["id"])
    print(f"blueprint {bp} provider {PID}: {len(colors)} colors x {len(sizes)} sizes = {len(vids)} variants")

    # apparel (tee/tiedye): design on the BACK + small MH logo on the front-left chest.
    dual = args.product in ("tee", "tiedye") and args.logo and Path(args.logo).exists()
    if args.printify_product:
        prod_id = args.printify_product
    else:
        art = (ROOT / "data" / "art" / f"{args.brand}__{args.concept}.png").read_bytes()
        design_id = c.upload_image(f"{args.slug}-print.png", art, dry_run=False)["id"]
        if dual:
            logo_id = c.upload_image(f"{args.slug}-logo.png", Path(args.logo).read_bytes(), dry_run=False)["id"]
            placements = [
                {"position": "back", "image_id": design_id, "x": 0.5, "y": 0.5, "scale": 0.95},
                {"position": "front", "image_id": logo_id, "x": 0.30, "y": 0.27, "scale": 0.16},
            ]
            res = c.create_product(title=args.name, description=args.description or args.name, blueprint_id=bp,
                                   variant_ids=vids, print_provider_id=PID, tags=["madd hatchery"],
                                   price_cents=price_cents, dry_run=False, product_type=args.product, placements=placements)
        else:
            res = c.create_product(title=args.name, description=args.description or args.name, blueprint_id=bp,
                                   variant_ids=vids, image_id=design_id, print_provider_id=PID,
                                   tags=["madd hatchery"], price_cents=price_cents, dry_run=False, product_type=args.product)
        prod_id = res["id"]
    print("printify product:", prod_id, "| dual-placement:", dual)

    full = c._request("GET", f"/shops/{c.shop_id}/products/{prod_id}.json")
    # The design lives on the BACK for dual-placement apparel — show that to shoppers.
    want_pos = "back" if dual else "front"
    imgs = [im for im in full.get("images", []) if im.get("position") == want_pos] \
        or [im for im in full.get("images", []) if im.get("position") == "front"] or full.get("images", [])

    # color-map the front mockups by sampling the garment color
    named_rgb = {col: tuple(int(COLOR_HEX.get(col, "#888888").lstrip("#")[i:i+2], 16) for i in (0, 2, 4)) for col in colors}
    color_img = {}
    for im in imgs:
        try:
            png = dl(im["src"]); rgb = shirt_rgb(png)
            nearest = min(colors, key=lambda col: sum((rgb[i] - named_rgb[col][i]) ** 2 for i in range(3)))
            if nearest not in color_img:  # first match wins
                im2 = Image.open(io.BytesIO(png)).convert("RGB"); im2.thumbnail((900, 900), Image.LANCZOS)
                b = io.BytesIO(); im2.save(b, "JPEG", quality=84, optimize=True)
                color_img[nearest] = base64.b64encode(b.getvalue()).decode()
        except Exception as e:
            print("  img skip:", str(e)[:60])

    variants = [{"printify_variant_id": matrix[col][sz], "color": col, "size": sz, "price_cents": price_cents}
                for col in matrix for sz in matrix[col]]
    colors_payload = [{"name": col, "hex": COLOR_HEX.get(col, "#999999"),
                       "image_base64": color_img.get(col), "image_ext": "jpg"}
                      for col in colors if color_img.get(col)]
    payload = {"slug": args.slug, "name": args.name, "category": args.category,
               "description": args.description, "price_cents": price_cents, "quantity": 999,
               "printify_product_id": prod_id, "variants": variants, "colors": colors_payload}
    r = http_post(args.api.rstrip("/") + "/api/admin/product", payload, token)
    print(f"storefront published: ok={r.get('ok')} variants={(r.get('product') or {}).get('variants')} colors={len(colors_payload)}")


if __name__ == "__main__":
    raise SystemExit(main())
