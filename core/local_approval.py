"""Local web approval/edit gate for TeeEmpire.

Simple, local-only (no ssh, no remote .206). Run with:
  python -m empire.cli gate --port 3333

Provides:
- Gallery of pending_review listings (concepts + mockups + scores).
- Approve / Reject (records review, can ship to Printify/Etsy if --live or via CLI).
- Edit/enhance: overlay text + visual tags on the art/mockup for shirts/mugs/stickers/posters.
- Variant picker (promote v1/v2 as primary).
- Re-render prompt tweak (calls image backend again with refined prompt).
- Multi-product aware mockup compositing (shirt, mug, sticker, poster).

Uses Flask for the UI (pip install flask if missing). Serves mockups from data/mockups.
Decisions feed the same store + review records as Telegram / old MC, so `empire ship` etc. work.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

_FLASK_AVAILABLE = False
try:
    from flask import Flask, jsonify, redirect, render_template_string, request, url_for  # type: ignore
    _FLASK_AVAILABLE = True
except Exception:  # pragma: no cover
    Flask = None  # type: ignore
    jsonify = redirect = render_template_string = request = url_for = None  # type: ignore
    def _no_flask(*a, **k):
        raise RuntimeError("Flask is not installed. Run: pip install flask  (then re-run `empire gate`)")

from . import brands as brands_mod
from . import designs as designs_mod
from . import images as images_mod
from . import ingest as ingest_mod
from . import printify as printify_mod
from . import etsy as etsy_mod
from .models import Brand
from .store import Store

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
MOCKUP_DIR = DATA_DIR / "mockups"
MOCKUP_DIR.mkdir(parents=True, exist_ok=True)

# Placements offered by the upload panel — mirror ingest._TEXT_PLACEMENTS.
_PLACEMENTS = ["back", "underneath", "left_sleeve", "right_sleeve", "neck"]

if _FLASK_AVAILABLE:
    app = Flask(__name__, static_folder=str(MOCKUP_DIR), static_url_path="/mockups")  # type: ignore
else:
    app = None  # type: ignore


def _get_store() -> Store:
    return Store()


def _load_pending(store: Store) -> List[Dict[str, Any]]:
    listings = store.list_listings(state="pending_review")
    items: List[Dict[str, Any]] = []
    seen = set()
    for l in listings:
        key = (l.brand, l.concept_slug)
        if key in seen:
            continue
        seen.add(key)
        concept = store.get_concept(l.brand, l.concept_slug)
        design = store.get_design(l.brand, l.concept_slug)
        if not concept or not design or not design.mockup_path:
            continue
        brand = brands_mod.load_brand(l.brand)
        items.append({
            "slug": concept.slug,
            "brand": l.brand,
            "brand_name": brand.name,
            "lane": concept.lane,
            "title": concept.product_title,
            "tagline": concept.tagline,
            "tags": concept.tags,
            "design_prompt": concept.design_prompt,
            "primary": design.mockup_path,
            "variants": design.variant_paths or ([design.mockup_path] if design.mockup_path else []),
            "judge_score": design.ocr_score,
            "judge_rationale": (design.design_notes or "").split("[judge]", 1)[-1].strip() if design.design_notes else "",
            "platform": l.platform,
            "external_id": l.external_id,
            "state": l.state,
            "product_type": (l.extra or {}).get("product_type") or "shirt",
        })
    return items


INDEX_HTML = """
<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Empire • Local Gate</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#0a0a0a;color:#eee;margin:0;padding:24px}
h1{font-size:20px;margin:0 0 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.card{background:#111;border:1px solid #222;border-radius:12px;overflow:hidden}
.thumb{width:100%;height:260px;object-fit:contain;background:#1a1a1a;display:block}
.meta{padding:12px 14px 14px}
h3{margin:0 0 4px;font-size:14px}
.brand{font-size:10px;opacity:.6;text-transform:uppercase;letter-spacing:.5px}
.tagline{font-size:12px;opacity:.85;margin:6px 0}
.score{font-size:11px;opacity:.6}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.btn{padding:6px 10px;font-size:12px;border-radius:6px;border:1px solid #333;background:#222;color:#ccc;cursor:pointer;text-decoration:none}
.btn.primary{background:#6cf;color:#000;border-color:#6cf}
.btn.danger{color:#f88;border-color:#522}
.btn:disabled{opacity:.4;cursor:not-allowed}
.alts{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px}
.alt img{width:100%;height:64px;object-fit:contain;background:#1a1a1a;border-radius:4px;border:1px solid #222}
form.inline{display:inline}
input,textarea,select{background:#1a1a1a;color:#eee;border:1px solid #333;border-radius:4px;padding:4px 6px;font-size:12px}
small{opacity:.5}
</style></head><body>
<h1>TeeEmpire • Local Approval Gate <small>(kie.ai + openrouter default)</small></h1>
<p><a href="/refresh">Refresh</a> | <a href="/picks">Export static picks HTML</a> | Pending: {{ count }}</p>
<details class="uploader" {{ 'open' if upload_msg else '' }} style="background:#101319;border:1px solid #243;border-radius:12px;padding:14px 16px;margin:0 0 18px">
  <summary style="font-size:15px;cursor:pointer">⬆️ Upload seed image + back/under text → RENDER bundle</summary>
  {% if upload_msg %}<p style="color:#6f6;font-size:12px;margin:8px 0 0">{{ upload_msg }}</p>{% endif %}
  <form action="/drop" method="post" enctype="multipart/form-data" style="margin-top:10px;display:grid;gap:10px;max-width:720px">
    <label>Seed image <input type="file" name="image" accept="image/png,image/jpeg,image/webp" required></label>
    <label>Title / prompt seed (optional)<br><input name="prompt" size="60" placeholder="e.g. Cryptid Field Guide — Mothman"></label>
    <label>Back / under text<br><input name="text" size="60" placeholder="literal words to stamp (leave blank for art-only)"></label>
    <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center">
      <label>Placement <select name="placement">
        {% for p in placements %}<option value="{{p}}" {{ 'selected' if p=='back' else '' }}>{{p}}</option>{% endfor %}
      </select></label>
      <label>Font <select name="font">
        {% for f in fonts %}<option value="{{f.key}}">{{f.label}}</option>{% endfor %}
      </select></label>
      <label>Color <select name="color">
        {% for c in colors %}<option value="{{c}}" {{ 'selected' if c=='white' else '' }}>{{c}}</option>{% endfor %}
      </select></label>
    </div>
    <div><button class="btn primary" type="submit">UPLOAD + RENDER (empire drop --live)</button>
      <small>writes to inbox, then fires one live render (tee/tiedye/mug/sticker/poster + text)</small></div>
  </form>
</details>
<div class="grid">
{% for it in items %}
<div class="card" data-slug="{{it.slug}}">
  <a href="/mockups/{{ it.primary | basename }}" target="_blank"><img class="thumb" src="/mockups/{{ it.primary | basename }}" alt="{{it.title}}"></a>
  <div class="meta">
    <h3>{{it.title}} <small>({{it.product_type}})</small></h3>
    <div class="brand">{{it.brand_name}} · {{it.lane}} · {{it.platform}}</div>
    <div class="tagline">{{it.tagline}}</div>
    <div class="score">score: {{ '%.0f'|format(it.judge_score*100) }}% {{it.judge_rationale}}</div>
    <div class="row">
      <form class="inline" action="/decide" method="post">
        <input type="hidden" name="slug" value="{{it.slug}}">
        <input type="hidden" name="decision" value="approve">
        <button class="btn primary" type="submit">✅ Approve + Ship</button>
      </form>
      <form class="inline" action="/decide" method="post">
        <input type="hidden" name="slug" value="{{it.slug}}">
        <input type="hidden" name="decision" value="reject">
        <button class="btn danger" type="submit">❌ Reject</button>
      </form>
    </div>
    <details style="margin-top:8px">
      <summary>Edit / Enhance (text, tags, overlay, re-render)</summary>
      <form action="/enhance" method="post" style="margin-top:6px">
        <input type="hidden" name="slug" value="{{it.slug}}">
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <label>Overlay text: <input name="overlay_text" value="{{it.title}}" size="28"></label>
          <label>Pos: <select name="overlay_region">
            <option value="0.10,0.06,0.80,0.28">top 80%</option>
            <option value="0.12,0.55,0.76,0.22">lower</option>
          </select></label>
          <label>Extra tag: <input name="visual_tag" value="" placeholder="RI" size="6"></label>
          <label>Product: <select name="product_type">
            <option value="shirt" {{ 'selected' if it.product_type=='shirt' else '' }}>Shirt</option>
            <option value="mug" {{ 'selected' if it.product_type=='mug' else '' }}>Mug</option>
            <option value="sticker" {{ 'selected' if it.product_type=='sticker' else '' }}>Sticker</option>
            <option value="poster" {{ 'selected' if it.product_type=='poster' else '' }}>Poster</option>
          </select></label>
        </div>
        <div style="margin-top:4px">
          <label>New prompt delta: <input name="prompt_delta" value="" size="40" placeholder="add subtle halftone texture"></label>
          <button class="btn" type="submit" name="action" value="overlay">Apply overlay + tags</button>
          <button class="btn" type="submit" name="action" value="rerender">Re-render with delta</button>
        </div>
        <div style="margin-top:4px">
          {% for v in it.variants %}
            <button class="btn" type="submit" name="promote" value="{{ v | basename }}">Use {{ loop.index0 or 'primary' }}</button>
          {% endfor %}
        </div>
      </form>
    </details>
    <div class="alts">
      {% for v in it.variants[1:4] %}
      <div class="alt"><img src="/mockups/{{ v | basename }}" alt="v"></div>
      {% endfor %}
    </div>
    <div style="margin-top:6px"><a class="btn" href="/mockups/{{ it.primary | basename }}" target="_blank">full</a></div>
  </div>
</div>
{% endfor %}
</div>
<script>
document.querySelectorAll('form').forEach(f => f.addEventListener('submit', () => {
  const b = f.querySelector('button[type="submit"]:focus') || f.querySelector('button');
  if (b) b.disabled = true;
}));
</script>
</body></html>
"""

PICKS_HTML = """
<!doctype html><html><head><meta charset="utf-8"><title>Empire Local Picks</title>
<style>body{background:#0a0a0a;color:#eee;font-family:sans-serif;padding:20px} .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px} .card{border:1px solid #222;background:#111;border-radius:8px;overflow:hidden} img{width:100%;height:220px;object-fit:contain;background:#1a1a1a} .m{padding:8px 10px;font-size:13px}</style>
</head><body><h1>Local Picks</h1><div class="grid">{{cards}}</div></body></html>
"""


def _basename(p: str) -> str:
    return Path(p).name


# Guard all Flask-specific top-level registration so the module can be imported
# even when flask is not installed (cmd_gate will give a clear error at runtime).
if _FLASK_AVAILABLE and app is not None:
    app.jinja_env.filters["basename"] = _basename  # type: ignore[attr-defined]

    @app.route("/")  # type: ignore[misc]
    def index():
        store = _get_store()
        items = _load_pending(store)
        return render_template_string(  # type: ignore
            INDEX_HTML, items=items, count=len(items),
            fonts=designs_mod.available_text_fonts(),
            colors=list(designs_mod.TEXT_COLORS.keys()),
            placements=_PLACEMENTS,
            upload_msg=request.args.get("msg", ""))

    @app.route("/refresh")  # type: ignore[misc]
    def refresh():
        return redirect(url_for("index"))  # type: ignore

    @app.route("/decide", methods=["POST"])  # type: ignore[misc]
    def decide():
        slug = request.form.get("slug", "")
        decision = request.form.get("decision", "")
        store = _get_store()
        for l in store.list_listings():
            if l.concept_slug == slug:
                if decision == "approve":
                    l.state = "approved"
                    store.upsert_listing(l)
                    store.record_review(l.brand, slug, "approved", reviewer="local-gate")
                    _ship_one(l)
                elif decision == "reject":
                    l.state = "rejected"
                    store.upsert_listing(l)
                    store.record_review(l.brand, slug, "rejected", reviewer="local-gate")
                break
        return redirect(url_for("index"))  # type: ignore

    @app.route("/drop", methods=["POST"])  # type: ignore[misc]
    def drop():
        """Save an uploaded seed image + back/under text spec into the local inbox,
        then fire `empire drop --live` so the merch bundle + stamped text render in
        one pass. Fully local — writes straight to the inbox, no remote round-trip.
        """
        upload = request.files.get("image")
        if not upload or not upload.filename:
            return redirect(url_for("index", msg="No image selected."))  # type: ignore
        ext = Path(upload.filename).suffix.lower()
        if ext not in ingest_mod.IMAGE_EXTS:
            return redirect(url_for(  # type: ignore
                "index", msg=f"Unsupported image type '{ext}'."))

        prompt = (request.form.get("prompt") or "").strip()
        text = (request.form.get("text") or "").strip()
        font = (request.form.get("font") or "bold_sans").strip()
        color = (request.form.get("color") or "white").strip()
        placement = (request.form.get("placement") or "back").strip()

        stem_seed = re.sub(r"[^a-z0-9]+", "-",
                           (prompt or Path(upload.filename).stem).lower()).strip("-")[:40]
        stem = f"{stem_seed or 'upload'}-{datetime.now().strftime('%m%d%H%M%S')}"

        inbox = ingest_mod.inbox_path()
        (inbox / f"{stem}{ext}").write_bytes(upload.read())
        spec = {"prompt": prompt, "text": text, "font": font,
                "color": color, "placement": placement}
        (inbox / f"{stem}{ingest_mod.SPEC_SUFFIX}").write_text(
            json.dumps(spec, indent=2), encoding="utf-8")

        # Fire one live render in the background; the gate fills in as Printify
        # finishes rendering (refresh to watch the cards arrive).
        log = DATA_DIR / f"drop-{stem}.log"
        cmd = [sys.executable, "-m", "empire", "drop", "--brand", "earl_biggers", "--live"]
        with open(log, "wb") as fh:
            subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=fh, stderr=subprocess.STDOUT)

        stamp = f" + '{text[:40]}' on {placement}" if text else ""
        return redirect(url_for(  # type: ignore
            "index", msg=f"Uploaded {stem}{ext}{stamp}. Live render started — refresh to watch cards arrive."))


def _ship_one(listing) -> Dict[str, Any]:
    """Ship a single approved listing. Re-uses the same logic as mc-poll / hitl."""
    try:
        brand = brands_mod.load_brand(listing.brand)
    except Exception:
        return {"error": "brand missing"}
    res: Dict[str, Any] = {}
    if listing.platform == "printify":
        client = printify_mod.PrintifyClient(shop_id=brand.printify_shop_id)
        res["printify"] = client.publish_product(listing.external_id, dry_run=False)
        listing.state = "live"
        listing.url = res["printify"].get("url") or listing.url
        Store().upsert_listing(listing)
    elif listing.platform == "etsy":
        client = etsy_mod.EtsyClient(shop_id=brand.etsy_shop_id)
        res["etsy"] = client.update_listing_state(int(listing.external_id), "active", dry_run=False)
        listing.state = "live"
        Store().upsert_listing(listing)
    return res


if _FLASK_AVAILABLE and app is not None:
    @app.route("/enhance", methods=["POST"])  # type: ignore[misc]
    def enhance():
        slug = request.form.get("slug", "")
        action = request.form.get("action") or ("promote" if request.form.get("promote") else "overlay")
        overlay_text = request.form.get("overlay_text", "")
        region_raw = request.form.get("overlay_region", "0.10,0.06,0.80,0.28")
        visual_tag = request.form.get("visual_tag", "")
        product_type = request.form.get("product_type", "shirt")
        prompt_delta = request.form.get("prompt_delta", "")
        promote = request.form.get("promote", "")

        store = _get_store()
        concept = None
        design = None
        listing = None
        for l in store.list_listings():
            if l.concept_slug == slug:
                listing = l
                concept = store.get_concept(l.brand, slug)
                design = store.get_design(l.brand, slug)
                break
        if not concept or not design:
            return redirect(url_for("index"))  # type: ignore

        extra = dict(listing.extra or {})
        extra["product_type"] = product_type
        listing.extra = extra
        store.upsert_listing(listing)

        if promote:
            for vp in design.variant_paths:
                if Path(vp).name == promote:
                    design.mockup_path = vp
                    store.upsert_design(design)
                    break
            return redirect(url_for("index"))  # type: ignore

        if action == "rerender" and prompt_delta:
            new_prompt = (concept.design_prompt or "") + " " + prompt_delta
            concept.design_prompt = new_prompt
            new_design = designs_mod.design_from_concept(brands_mod.load_brand(concept.brand), concept)
            new_design = designs_mod.build_mockup(brands_mod.load_brand(concept.brand), concept, new_design, dry_run=False)
            all_vars = (design.variant_paths or []) + (new_design.variant_paths or [])
            design.variant_paths = list(dict.fromkeys(all_vars))
            design.mockup_path = new_design.mockup_path
            design.ocr_score = new_design.ocr_score
            design.variant_count = len(design.variant_paths)
            design.design_notes = new_design.design_notes
            store.upsert_design(design)
            return redirect(url_for("index"))  # type: ignore

        try:
            raw = Path(design.mockup_path).read_bytes() if design.mockup_path else b""
            if raw:
                region = tuple(float(x) for x in region_raw.split(",")[:4])
                tagged = designs_mod.overlay_text_panel(
                    raw,
                    text=overlay_text or concept.product_title,
                    region=region,
                )
                if visual_tag:
                    tagged = designs_mod.overlay_text_panel(
                        tagged,
                        text=visual_tag,
                        region=(0.78, 0.82, 0.20, 0.12),
                        panel_color="#222",
                        border_color="#D49A2C",
                        border_width=2,
                    )
                outp = MOCKUP_DIR / f"{concept.brand}__{slug}__edited.png"
                outp.write_bytes(tagged)
                design.variant_paths = [str(outp)] + [p for p in (design.variant_paths or []) if p != str(outp)]
                design.mockup_path = str(outp)
                store.upsert_design(design)
        except Exception as e:
            print("enhance overlay error:", e)

        return redirect(url_for("index"))  # type: ignore


if _FLASK_AVAILABLE and app is not None:
    @app.route("/picks")  # type: ignore[misc]
    def picks():
        """Export a static self-contained picks page (no server needed)."""
        store = _get_store()
        items = _load_pending(store)
        cards = []
        for it in items:
            p = Path(it["primary"]).name
            cards.append(f'''
            <div class="card">
              <img src="/mockups/{p}">
              <div class="m"><b>{it["title"]}</b><br><small>{it["brand_name"]} · {it["product_type"]}</small><br>{it["tagline"]}</div>
            </div>''')
        html = PICKS_HTML.replace("{{cards}}", "".join(cards))
        out = DATA_DIR / "local_picks.html"
        out.write_text(html)
        return f"<p>Wrote {out}. <a href='/mockups/'>mockups</a> | <a href='/'>back to gate</a></p><p>Open the file directly for a static gallery.</p>"


def run_gate(host: str = "127.0.0.1", port: int = 3333, debug: bool = False) -> None:
    """Entry point for CLI. Starts the local-only approval/edit web UI."""
    if not _FLASK_AVAILABLE or app is None:
        _no_flask()
    print(f"Starting local Empire gate at http://{host}:{port} (Ctrl-C to stop)")
    print("Open the URL in your browser. Approve/edit there, then use `empire ship --brand X --live` or the gate's approve+ship buttons.")
    app.run(host=host, port=port, debug=debug, use_reloader=False)  # type: ignore


if __name__ == "__main__":
    run_gate()
