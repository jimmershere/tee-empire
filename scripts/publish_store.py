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


REMBG_VENV = os.environ.get("REMBG_PY", "/tmp/rembg-venv/bin/python")


def transparent_pngs(png_list):
    """Strip the white/studio background from each mockup -> transparent RGBA PNG.

    rembg (U2Net) handles light AND dark shirts (unlike corner-floodfill, which eats
    white garments). One venv subprocess loads the model once and processes the whole
    batch. Falls back to the original bytes (composited on white) if rembg is unavailable.
    """
    if not png_list:
        return []
    import subprocess, tempfile
    out_bytes = list(png_list)  # default = original (fallback)
    if Path(REMBG_VENV).exists():
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            for i, png in enumerate(png_list):
                (tdp / f"in_{i}.png").write_bytes(png)
            script = (
                "import sys,glob,os\n"
                "from rembg import remove, new_session\n"
                "d=sys.argv[1]; s=new_session('u2net')\n"
                "for f in sorted(glob.glob(os.path.join(d,'in_*.png'))):\n"
                "    o=f.replace('in_','out_')\n"
                "    open(o,'wb').write(remove(open(f,'rb').read(), session=s))\n"
            )
            try:
                subprocess.run([REMBG_VENV, "-c", script, str(tdp)], check=True,
                               capture_output=True, timeout=600)
                for i in range(len(png_list)):
                    op = tdp / f"out_{i}.png"
                    if op.exists():
                        out_bytes[i] = op.read_bytes()
            except Exception as e:
                print("  rembg batch failed, using opaque mockups:", str(e)[:120])
    else:
        print("  rembg venv missing at", REMBG_VENV, "- using opaque mockups")
    # downscale + normalize to RGBA PNG for the storefront
    final = []
    for b in out_bytes:
        try:
            im = Image.open(io.BytesIO(b)).convert("RGBA")
            im.thumbnail((900, 900), Image.LANCZOS)
            buf = io.BytesIO(); im.save(buf, "PNG", optimize=True)
            final.append(buf.getvalue())
        except Exception:
            final.append(b)
    return final


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
            # scale < 1 + y slightly up so the TOP of the art isn't clipped off the print area.
            placements = [
                {"position": "back", "image_id": design_id, "x": 0.5, "y": 0.46, "scale": 0.72},
                {"position": "front", "image_id": logo_id, "x": 0.31, "y": 0.26, "scale": 0.15},
            ]
            res = c.create_product(title=args.name, description=args.description or args.name, blueprint_id=bp,
                                   variant_ids=vids, print_provider_id=PID, tags=["madd hatchery"],
                                   price_cents=price_cents, dry_run=False, product_type=args.product, placements=placements)
        else:
            res = c.create_product(title=args.name, description=args.description or args.name, blueprint_id=bp,
                                   variant_ids=vids, image_id=design_id, print_provider_id=PID,
                                   tags=["madd hatchery"], price_cents=price_cents, dry_run=False, product_type=args.product,
                                   image_transform={"x": 0.5, "y": 0.44, "scale": 0.66})
        prod_id = res["id"]
    print("printify product:", prod_id, "| dual-placement:", dual)

    # Printify renders mockups asynchronously — poll until BOTH positions exist (dual)
    # or front exists (single), so we don't miss the front-of-shirt view.
    import time as _time
    need_back = dual
    for _try in range(12):
        full = c._request("GET", f"/shops/{c.shop_id}/products/{prod_id}.json")
        all_imgs = full.get("images", [])
        have_front = any(im.get("position") == "front" for im in all_imgs)
        have_back = any(im.get("position") == "back" for im in all_imgs)
        if have_front and (have_back or not need_back):
            break
        print(f"  waiting for mockups... (front={have_front} back={have_back})")
        _time.sleep(5)
    back_imgs = [im for im in all_imgs if im.get("position") == "back"]
    front_imgs = [im for im in all_imgs if im.get("position") == "front"]
    # Primary view = where the main design lives (back for dual apparel, else front).
    primary_imgs = (back_imgs if dual else front_imgs) or front_imgs or all_imgs
    secondary_imgs = front_imgs if dual else []  # the front-with-chest-logo view

    named_rgb = {col: tuple(int(COLOR_HEX.get(col, "#888888").lstrip("#")[i:i+2], 16) for i in (0, 2, 4)) for col in colors}

    def map_by_color(imgs):
        """Download mockups, map each to the nearest wanted color (sampling the garment)."""
        out = {}
        for im in imgs:
            try:
                png = dl(im["src"]); rgb = shirt_rgb(png)
                nearest = min(colors, key=lambda col: sum((rgb[i] - named_rgb[col][i]) ** 2 for i in range(3)))
                if nearest not in out:
                    out[nearest] = png
            except Exception as e:
                print("  img skip:", str(e)[:60])
        return out

    primary_raw = map_by_color(primary_imgs)
    secondary_raw = map_by_color(secondary_imgs) if secondary_imgs else {}
    print(f"  mockups: back={len(back_imgs)} front={len(front_imgs)} mapped primary={len(primary_raw)} front={len(secondary_raw)}")

    # Transparent backgrounds for ALL mockups (rembg handles light AND dark shirts).
    keys = list(primary_raw.keys()); skeys = list(secondary_raw.keys())
    allpng = [primary_raw[k] for k in keys] + [secondary_raw[k] for k in skeys]
    tp = transparent_pngs(allpng)
    primary_b64 = {keys[i]: base64.b64encode(tp[i]).decode() for i in range(len(keys))}
    secondary_b64 = {skeys[i]: base64.b64encode(tp[len(keys) + i]).decode() for i in range(len(skeys))}

    variants = [{"printify_variant_id": matrix[col][sz], "color": col, "size": sz, "price_cents": price_cents}
                for col in matrix for sz in matrix[col]]
    colors_payload = [{"name": col, "hex": COLOR_HEX.get(col, "#999999"), "image_ext": "png",
                       "image_base64": primary_b64.get(col),
                       "front_image_base64": secondary_b64.get(col)}
                      for col in colors if primary_b64.get(col)]
    payload = {"slug": args.slug, "name": args.name, "category": args.category,
               "description": args.description, "price_cents": price_cents, "quantity": 999,
               "printify_product_id": prod_id, "variants": variants, "colors": colors_payload}
    r = http_post(args.api.rstrip("/") + "/api/admin/product", payload, token)
    print(f"storefront published: ok={r.get('ok')} variants={(r.get('product') or {}).get('variants')} colors={len(colors_payload)}")


if __name__ == "__main__":
    raise SystemExit(main())
