#!/usr/bin/env python3
"""Publish a single-design merch item (sticker / mug / bottle) as a REAL Printify
product to the Madd Hatchery storefront. These blueprints have sizes (and at most a
single surface/color), so they're sold as one design across size variants.

Reuses publish_store's transparency helpers (rembg for mockups). Writes a storefront
payload to --dump-dir (for droplet self-publish) or POSTs directly with --api.

Usage:
  python scripts/publish_merch_single.py --product sticker --slug mh-logo-sticker \
     --name "Madd Hatchery Logo Sticker" --category sticker --price 5 \
     --design /app/maddhatch/public/assets/v3/logo_2026.png --dump-dir /tmp/merch
"""
from __future__ import annotations
import argparse, base64, io, json, os, sys, types, importlib.util, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for n, d in (("empire", "empire"), ("empire.core", "core")):
    m = types.ModuleType(n); m.__path__ = [str(ROOT / d)]; m.__package__ = n; sys.modules[n] = m
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.split("#", 1)[0].strip())

from empire.core import printify as P
from PIL import Image

# reuse transparent_pngs / floodfill_transparent / dl from publish_store
_ps_spec = importlib.util.spec_from_file_location("ps", str(ROOT / "scripts" / "publish_store.py"))
ps = importlib.util.module_from_spec(_ps_spec); _ps_spec.loader.exec_module(ps)

BLUEPRINT = {"sticker": 400, "mug": 478, "bottle": 887}
# logo print scale per product (fraction of print area)
SCALE = {"sticker": 0.95, "mug": 0.7, "bottle": 0.6}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True, choices=list(BLUEPRINT))
    ap.add_argument("--slug", required=True); ap.add_argument("--name", required=True)
    ap.add_argument("--category", required=True); ap.add_argument("--price", type=float, required=True)
    ap.add_argument("--design", required=True, help="print graphic (e.g. the MH logo png)")
    ap.add_argument("--api", default=os.getenv("MADDHATCHERY_API_URL", "https://maddhatchery.com"))
    ap.add_argument("--dump-dir", default="")
    args = ap.parse_args()

    price_cents = int(round(args.price * 100))
    bp = BLUEPRINT[args.product]
    c = P.PrintifyClient(shop_id=os.environ.get("PRINTIFY_SHOP_ID"))
    prov = c.list_print_providers(bp); pl = prov if isinstance(prov, list) else prov.get("data", prov)
    PID = pl[0]["id"]
    v2 = c.list_variants(bp, PID); vl = v2.get("variants") if isinstance(v2, dict) else v2
    vids = [v["id"] for v in vl]
    # label for the single colour group = the surface/colour option value, else a neutral label
    def opt_color(v):
        o = v.get("options", {})
        return o.get("color") or o.get("surface") or "Standard"
    color_label = opt_color(vl[0]) if vl else "Standard"
    print(f"blueprint {bp} provider {PID}: {len(vids)} size variants, colour group '{color_label}'")

    # print art: strip any white box (logo is usually already transparent → no-op)
    art = ps.floodfill_transparent(Path(args.design).read_bytes())
    design_id = c.upload_image(f"{args.slug}-print.png", art, dry_run=False)["id"]
    sc = SCALE[args.product]
    res = c.create_product(title=args.name, description=args.name, blueprint_id=bp,
                           variant_ids=vids, image_id=design_id, print_provider_id=PID,
                           tags=["madd hatchery"], price_cents=price_cents, dry_run=False,
                           product_type=args.product, image_transform={"x": 0.5, "y": 0.5, "scale": sc})
    prod_id = res["id"]
    print("printify product:", prod_id)

    # one mockup is enough (single design, single colour); poll until rendered
    full = {}
    for _ in range(12):
        full = c._request("GET", f"/shops/{c.shop_id}/products/{prod_id}.json")
        if full.get("images"):
            break
        time.sleep(5)
    imgs = full.get("images", [])
    default = next((im for im in imgs if im.get("is_default")), imgs[0] if imgs else None)
    img_b64 = None
    if default:
        raw = ps.dl(default["src"])
        tp = ps.transparent_pngs([raw])  # rembg the mockup -> transparent
        img_b64 = base64.b64encode(tp[0]).decode()

    variants = [{"printify_variant_id": v["id"], "color": color_label,
                 "size": v.get("options", {}).get("size") or "One Size", "price_cents": price_cents}
                for v in vl]
    colors_payload = [{"name": color_label, "hex": "#f4f4f2", "image_ext": "png", "image_base64": img_b64}]
    payload = {"slug": args.slug, "name": args.name, "category": args.category,
               "description": args.name, "price_cents": price_cents, "quantity": 999,
               "printify_product_id": prod_id, "variants": variants, "colors": colors_payload}

    if args.dump_dir:
        outp = Path(args.dump_dir); outp.mkdir(parents=True, exist_ok=True)
        f = outp / f"{args.slug}.json"; f.write_text(json.dumps(payload))
        print(f"payload dumped: {f} ({f.stat().st_size // 1024} KB, {len(variants)} variants)")
        return 0
    token = os.environ["MADDHATCHERY_ADMIN_TOKEN"]
    r = ps.http_post(args.api.rstrip("/") + "/api/admin/product", payload, token)
    print(f"published: ok={r.get('ok')} variants={(r.get('product') or {}).get('variants')}")


if __name__ == "__main__":
    raise SystemExit(main())
