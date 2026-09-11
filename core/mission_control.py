"""Publish empire best-picks to Mission Control on .206.

Workflow:
  1. rsync the mockup PNGs (primary + variants) to /home/floor2/.openclaw/
     workspace/mission-control/public/empire-picks/
  2. Generate /public/empire-picks.html with a gallery of all picks
     (primary mockup featured + alternates clickable)
  3. User opens http://localhost:3333/public/empire-picks.html on .206

SSH transport: id_ed25519 ProxyJump through floor2@192.168.1.206 to reach the
target (which is .206 itself). Since the dest IS .206, we just use floor2 as
the target user — no ProxyJump needed.
"""
from __future__ import annotations

import html
import json
import os
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import designs as designs_mod
from .models import Brand, Concept, Design
from .store import Store

MC_HOST = os.getenv("MC_HOST", "floor2@192.168.1.206")
MC_PUBLIC = os.getenv("MC_PUBLIC_DIR",
                      "/home/floor2/.openclaw/workspace/mission-control/public/empire-picks")
MC_DATA = os.getenv("MC_DATA_DIR",
                    "/home/floor2/.openclaw/workspace/mission-control/data")
MC_PENDING_FILE = "empire-pending.json"
MC_DECISIONS_FILE = "empire-decisions.jsonl"
MC_API_BASE = os.getenv("MC_API_BASE", "http://192.168.1.206:3333")
SSH_KEY = os.getenv("MC_SSH_KEY", str(Path.home() / ".ssh" / "floor2_mount"))
SSH_BASE = ["ssh", "-i", SSH_KEY,
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=accept-new"]


def publish_picks(store: Optional[Store] = None,
                  brand_filter: Optional[str] = None,
                  limit: int = 40) -> dict:
    """Sync mockups for recent designs to MC, regenerate the index HTML.

    Returns a summary dict with counts + the public URL.
    """
    store = store or Store()
    listings = store.list_listings(brand=brand_filter)
    # Latest first (already ordered by updated_at DESC in list_listings).
    seen = set()
    designs: List[tuple] = []  # (Brand-loaded-later, Concept, Design)
    for l in listings:
        key = (l.brand, l.concept_slug)
        if key in seen:
            continue
        seen.add(key)
        concept = store.get_concept(l.brand, l.concept_slug)
        design = store.get_design(l.brand, l.concept_slug)
        if not concept or not design or not design.mockup_path:
            continue
        designs.append((l.brand, concept, design, l))
        if len(designs) >= limit:
            break

    # Stage local dir to rsync from.
    stage = Path(__file__).resolve().parents[1] / "data" / "mc_stage"
    stage.mkdir(parents=True, exist_ok=True)
    # Clear existing staged files so the rsync mirrors current state.
    for p in stage.glob("*"):
        if p.is_file():
            p.unlink()

    asset_map: dict = {}
    for brand_slug, concept, design, listing in designs:
        for variant_path in (design.variant_paths or [design.mockup_path]):
            src = Path(variant_path)
            if not src.exists():
                continue
            dest = stage / src.name
            dest.write_bytes(src.read_bytes())
        asset_map[concept.slug] = {
            "primary": Path(design.mockup_path).name,
            "variants": [Path(p).name for p in design.variant_paths],
        }

    # Build HTML.
    html_str = _render_html(designs, asset_map)
    (stage / "index.html").write_text(html_str)

    # rsync stage → MC_HOST:MC_PUBLIC (image gallery)
    _ensure_remote_dir()
    rsync_cmd = [
        "rsync", "-az", "--delete",
        "-e", " ".join(SSH_BASE),
        f"{stage}/", f"{MC_HOST}:{MC_PUBLIC}/",
    ]
    subprocess.run(rsync_cmd, check=True, capture_output=True)

    # Also push empire-pending.json into MC's data dir (used by the backend
    # route /api/empire/items so the page can fetch & merge with decisions).
    pending = {"items": [_item_for_pending(b, c, d, l, asset_map) for b, c, d, l in designs]}
    pending_local = stage.parent / MC_PENDING_FILE
    pending_local.write_text(json.dumps(pending, indent=2))
    subprocess.run(
        SSH_BASE + [MC_HOST, f"mkdir -p {MC_DATA}"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["scp", "-i", SSH_KEY, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
         str(pending_local), f"{MC_HOST}:{MC_DATA}/{MC_PENDING_FILE}"],
        check=True, capture_output=True,
    )

    return {
        "published": len(designs),
        "host": MC_HOST,
        "remote_dir": MC_PUBLIC,
        "pending_file": f"{MC_DATA}/{MC_PENDING_FILE}",
        "public_url": "http://localhost:3333/public/empire-picks/index.html",
    }


def _item_for_pending(brand_slug: str, concept, design, listing, asset_map: dict) -> dict:
    am = asset_map.get(concept.slug, {})
    rationale = ""
    if design.design_notes and "[judge]" in design.design_notes:
        rationale = design.design_notes.split("[judge]", 1)[1].strip()
    extra = listing.extra or {}
    return {
        "slug": concept.slug,
        "brand": brand_slug,
        "lane": concept.lane,
        "title": concept.product_title,
        "tagline": concept.tagline,
        "primary": am.get("primary", ""),
        "variants": am.get("variants", []),
        "judge_score": design.ocr_score,
        "judge_rationale": rationale,
        "platform": listing.platform,
        "external_id": listing.external_id,
        "state": listing.state,
        "url": listing.url or "",
        "product": extra.get("product", ""),
        "product_label": extra.get("product_label", ""),
    }


def fetch_decisions() -> list:
    """Pull empire-decisions.jsonl from .206 — used by `empire mc-poll`."""
    result = subprocess.run(
        SSH_BASE + [MC_HOST, f"cat {MC_DATA}/{MC_DECISIONS_FILE} 2>/dev/null || true"],
        capture_output=True, text=True, check=True,
    )
    decisions = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            decisions.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return decisions


def mark_applied(slugs: list) -> None:
    """Append empire-applied.jsonl entries so mc-poll knows what's been processed."""
    if not slugs:
        return
    lines = [json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                         "slug": s, "applied": True}) for s in slugs]
    payload = "\n".join(lines) + "\n"
    subprocess.run(
        SSH_BASE + [MC_HOST, f"cat >> {MC_DATA}/empire-applied.jsonl"],
        input=payload, text=True, check=True, capture_output=True,
    )


def fetch_applied() -> set:
    """Return the set of slugs already applied (so mc-poll doesn't re-do them)."""
    result = subprocess.run(
        SSH_BASE + [MC_HOST, f"cat {MC_DATA}/empire-applied.jsonl 2>/dev/null || true"],
        capture_output=True, text=True, check=True,
    )
    applied = set()
    for line in result.stdout.splitlines():
        try:
            entry = json.loads(line)
            if entry.get("applied") and entry.get("slug"):
                applied.add(entry["slug"])
        except json.JSONDecodeError:
            continue
    return applied


def _ensure_remote_dir() -> None:
    subprocess.run(SSH_BASE + [MC_HOST, f"mkdir -p {MC_PUBLIC}"],
                   check=True, capture_output=True)


def _render_html(designs: list, asset_map: dict) -> str:
    rows_html: List[str] = []
    # Build the add-text font dropdown once, grouped by category, from the
    # fonts actually installed + loadable on this machine.
    _groups: dict = {}
    for f in designs_mod.available_text_fonts():
        _groups.setdefault(f["category"], []).append(f)
    font_opts = "".join(
        '<optgroup label="{}">{}</optgroup>'.format(
            html.escape(cat),
            "".join('<option value="{}">{}</option>'.format(html.escape(f["key"]), html.escape(f["label"]))
                    for f in items))
        for cat, items in _groups.items()
    )
    for brand_slug, concept, design, listing in designs:
        slug = concept.slug
        am = asset_map.get(slug, {})
        primary = am.get("primary", "")
        variants = am.get("variants", [])
        is_pending = primary.endswith("_placeholder.png")
        listing_link = listing.url or ""
        # Build alternate thumbnails inline (clickable to swap primary). Hidden
        # while the card is still on its rendering placeholder.
        alts_inline = ""
        if not is_pending and len(variants) > 1:
            thumbs = []
            for i, vname in enumerate(variants):
                if vname == primary:
                    continue
                if "__v1." in vname:
                    swap = "swap_v1"
                elif "__v2." in vname:
                    swap = "swap_v2"
                elif "__v3." in vname:
                    swap = "swap_v3"
                else:
                    swap = ""
                thumbs.append(
                    f'<div class="alt-cell">'
                    f'  <a href="{html.escape(vname)}" target="_blank">'
                    f'    <img class="alt-thumb" src="{html.escape(vname)}" alt="v{i}">'
                    f'  </a>'
                    + (f'  <button class="alt-pick" data-decision="{swap}" data-slug="{html.escape(slug)}">use this</button>'
                       if swap else "")
                    + f'</div>'
                )
            alts_inline = ('<div class="alts-wrap"><span class="alts-label">Other colors</span>'
                           '<div class="alts-grid">' + "".join(thumbs) + "</div></div>")
        extra = listing.extra or {}
        product_label = extra.get("product_label", "") or extra.get("product", "")
        prod_html = (f'<span class="prod-tag">{html.escape(product_label)}</span>'
                     if product_label else "")
        esc_slug = html.escape(slug)
        product_key = (extra.get("product") or "").lower()
        # Placement options are filtered to what the blueprint actually supports.
        # Only the tees (front/back/sleeves/neck) have secondary print areas; mugs,
        # stickers and posters are single-area, so text can only stack on the face.
        if product_key in ("tee", "tshirt", "shirt", "tiedye"):
            placements = [("back", "Back"), ("left_sleeve", "Left sleeve"),
                          ("right_sleeve", "Right sleeve"), ("neck", "Neck label"),
                          ("underneath", "Underneath (front)")]
        else:
            placements = [("underneath", "On front (lower)")]
        placement_opts = "".join(f'<option value="{v}">{l}</option>' for v, l in placements)
        color_opts = ('<option value="white">White</option>'
                      '<option value="black">Black</option>'
                      '<option value="red">Red</option>'
                      '<option value="navy">Navy</option>'
                      '<option value="gold">Gold</option>'
                      '<option value="grey">Grey</option>')
        pending_badge = '<span class="badge rendering">⏳ rendering…</span>' if is_pending else ""
        rows_html.append(textwrap.dedent(f"""\
            <article class="card{' is-pending' if is_pending else ''}" data-slug="{html.escape(slug)}">
              <a href="{html.escape(primary)}" target="_blank" class="thumb-link">
                <img class="thumb" src="{html.escape(primary)}" alt="{html.escape(concept.product_title)}" loading="lazy">
                {pending_badge}
              </a>
              <div class="meta">
                <div class="tagrow">{prod_html}<span class="brand-chip">{html.escape(brand_slug)}</span></div>
                <h3>{html.escape(concept.product_title)}</h3>
                <p class="tagline">{html.escape(concept.tagline)}</p>
                <div class="row decide-row">
                  <button class="btn approve" data-decision="approve" data-slug="{html.escape(slug)}">✓ Approve</button>
                  <button class="btn reject" data-decision="reject" data-slug="{html.escape(slug)}">✕ Reject</button>
                </div>
                <div class="addtext-row">
                  <input class="addtext-input" type="text" data-refine-for="{esc_slug}"
                         placeholder="Add text — e.g. add &quot;Est. 2024&quot; under the art">
                  <button class="btn addtext-go" data-refine-slug="{esc_slug}">＋ ADD-TEXT</button>
                </div>
                <details class="exact">
                  <summary>Exact text · pick font, color &amp; placement</summary>
                  <div class="exact-body">
                    <input class="at-text" type="text" data-at-text="{esc_slug}"
                           placeholder="Words to print (e.g. FULLY BAKED)">
                    <div class="at-row">
                      <select class="at-font" data-at-font="{esc_slug}" title="Font">{font_opts}</select>
                      <select class="at-color" data-at-color="{esc_slug}" title="Color">{color_opts}</select>
                      <select class="at-place" data-at-place="{esc_slug}" title="Placement">{placement_opts}</select>
                    </div>
                    <button class="btn stamp-btn" data-addtext-slug="{esc_slug}">Stamp exact text</button>
                  </div>
                </details>
                <p class="status-line" data-status-for="{esc_slug}"></p>
                {alts_inline}
                <div class="row footer-row">
                  <a class="link" href="{html.escape(primary)}" target="_blank">Open full image</a>
                  {f'<a class="link" href="{html.escape(listing_link)}" target="_blank">View on Printify ↗</a>' if listing_link else ''}
                </div>
              </div>
            </article>
        """))

    return textwrap.dedent("""\
        <!DOCTYPE html>
        <html lang="en"><head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Portwright Press — Best Picks</title>
          <link href="https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
          <style>
            :root {
              --bg: #0B1018; --panel: #121C2A; --panel-2: #16212F;
              --line: #22324C; --text: #E7EBEF; --muted: #93A6BC;
              --accent: #A6E84A; --accent-soft: rgba(166,232,74,.16);
              --orange: #EF6A28; --cream: #ECE4D2;
              --green: #A6E84A; --red: #FF5A4D;
            }
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: 'Saira Condensed', sans-serif;
                   background: var(--bg);
                   background-image: linear-gradient(rgba(34,50,76,.25) 1px,transparent 1px),linear-gradient(90deg,rgba(34,50,76,.25) 1px,transparent 1px);
                   background-size: 48px 48px;
                   color: var(--text); padding: 28px clamp(16px,4vw,40px); }
            header { display: flex; align-items: center; justify-content: space-between;
                     gap: 16px; margin-bottom: 26px; }
            .brandmark { display: flex; align-items: center; gap: 12px; }
            .dot { width: 11px; height: 11px; border-radius: 50%;
                   background: var(--green); box-shadow: 0 0 12px var(--green); }
            h1 { font-size: 21px; font-weight: 700; letter-spacing: -.4px; }
            h1 small { display: block; font-size: 12px; font-weight: 500;
                       color: var(--muted); letter-spacing: 0; margin-top: 2px; }
            .meta-stamp { font-size: 12px; color: var(--muted); text-align: right; }
            .grid { display: grid; gap: 22px;
                    grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); }
            .card { background: var(--panel); border: 1px solid var(--line);
                    border-radius: 18px; overflow: hidden; display: flex; flex-direction: column;
                    box-shadow: 0 8px 30px rgba(0,0,0,.25);
                    transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease; }
            .card:hover { transform: translateY(-3px); border-color: rgba(255,255,255,.22);
                          box-shadow: 0 14px 40px rgba(0,0,0,.4); }
            .thumb-link { position: relative; display: block; background: #0c0e12; }
            .thumb { width: 100%; height: 300px; object-fit: contain; display: block; }
            .badge { position: absolute; top: 10px; left: 10px; font-size: 11px;
                     font-weight: 600; padding: 5px 10px; border-radius: 999px;
                     background: rgba(0,0,0,.6); color: #cfd6e4; backdrop-filter: blur(4px); }
            .badge.rendering { color: #ffd98a; }
            .is-pending .thumb { animation: pulse 1.6s ease-in-out infinite; }
            @keyframes pulse { 0%,100% { opacity: .55; } 50% { opacity: .9; } }
            .meta { padding: 15px 17px 17px; display: flex; flex-direction: column; gap: 9px; flex: 1; }
            .tagrow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
            .prod-tag { font-size: 11px; font-weight: 700; color: var(--accent);
                        background: var(--accent-soft); padding: 3px 9px; border-radius: 999px; }
            .brand-chip { font-size: 10px; letter-spacing: .6px; text-transform: uppercase;
                          color: var(--muted); }
            .meta h3 { font-size: 15.5px; font-weight: 650; line-height: 1.3; }
            .tagline { font-size: 13px; color: var(--muted); line-height: 1.45; }
            .row { display: flex; gap: 8px; flex-wrap: wrap; }
            .decide-row { margin-top: 2px; }
            .decide-row .btn { flex: 1; }
            .btn { display: inline-flex; align-items: center; justify-content: center;
                   padding: 10px 14px; font-size: 13px; font-weight: 600; border-radius: 10px;
                   text-decoration: none; color: var(--text); cursor: pointer; font-family: inherit;
                   background: var(--panel-2); border: 1px solid var(--line); transition: all .12s ease; }
            .btn:hover { background: rgba(255,255,255,.09); }
            .btn:disabled { opacity: .45; cursor: not-allowed; }
            .btn.approve { color: #06301c; background: var(--green); border-color: var(--green); }
            .btn.approve:hover { filter: brightness(1.08); }
            .btn.reject { color: var(--red); border-color: rgba(255,107,107,.4); background: rgba(255,107,107,.08); }
            .btn.reject:hover { background: rgba(255,107,107,.16); }
            .addtext-row { display: flex; gap: 7px; }
            .addtext-input { flex: 1; min-width: 0; padding: 9px 11px; font-size: 12.5px;
                             border-radius: 10px; background: var(--panel-2);
                             border: 1px solid var(--line); color: var(--text); font-family: inherit; }
            .addtext-input::placeholder { color: #6b7488; }
            .addtext-input:focus { outline: none; border-color: var(--accent); }
            .btn.addtext-go { white-space: nowrap; color: var(--accent);
                              border-color: rgba(91,140,255,.45); background: var(--accent-soft); }
            .btn.addtext-go:hover { background: rgba(91,140,255,.28); }
            .exact { border: 1px solid var(--line); border-radius: 10px;
                     background: rgba(255,255,255,.02); }
            .exact summary { cursor: pointer; font-size: 12px; padding: 9px 12px;
                             color: var(--muted); list-style: none; }
            .exact summary::-webkit-details-marker { display: none; }
            .exact summary::before { content: "▸ "; color: var(--accent); }
            .exact[open] summary::before { content: "▾ "; }
            .exact[open] summary { color: var(--text); }
            .exact-body { display: flex; flex-direction: column; gap: 7px; padding: 0 12px 12px; }
            .at-row { display: flex; gap: 6px; }
            .at-text, .at-row select { padding: 8px 9px; font-size: 12px; border-radius: 9px;
                            background: var(--panel-2); border: 1px solid var(--line);
                            color: var(--text); font-family: inherit; }
            .at-row select { flex: 1; min-width: 0; }
            .at-text:focus, .at-row select:focus { outline: none; border-color: var(--accent); }
            .btn.stamp-btn { align-self: flex-start; color: var(--accent);
                             border-color: rgba(91,140,255,.35); }
            .status-line { font-size: 12px; min-height: 15px; color: var(--accent); font-weight: 500; }
            .alts-wrap { border-top: 1px solid var(--line); padding-top: 11px; }
            .alts-label { font-size: 10px; letter-spacing: .6px; text-transform: uppercase;
                          color: var(--muted); }
            .alts-grid { display: grid; grid-template-columns: repeat(3, 1fr);
                         gap: 8px; margin-top: 8px; }
            .alt-cell { display: flex; flex-direction: column; gap: 4px; align-items: center; }
            .alt-thumb { width: 100%; height: 76px; object-fit: contain; background: #0c0e12;
                         border-radius: 8px; border: 1px solid var(--line); display: block; }
            .alt-pick { font-size: 10px; padding: 5px 6px; background: var(--panel-2);
                        color: var(--muted); border: 1px solid var(--line);
                        border-radius: 6px; cursor: pointer; width: 100%; font-family: inherit; }
            .alt-pick:hover { background: var(--accent-soft); color: var(--accent); }
            .footer-row { margin-top: auto; padding-top: 11px; border-top: 1px solid var(--line);
                          gap: 16px; }
            .link { font-size: 12px; color: var(--accent); text-decoration: none; }
            .link:hover { text-decoration: underline; }
            .empty { text-align: center; color: var(--muted); padding: 80px 20px; font-size: 14px; }
          </style>
        </head>
        <body>
          <header>
            <div class="brandmark">
              <span class="dot"></span>
              <div>
                <div style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:3px;color:var(--accent);text-transform:uppercase">Built in Port · Proven at Sea</div>
                <h1 style="font-weight:800;letter-spacing:-.6px">Portwright Press <small>Best Picks · approve, reject or add text</small></h1>
              </div>
            </div>
            <span class="meta-stamp">$count items<br>refreshed $stamp</span>
          </header>
          $body
          <script>
            async function decide(btn) {
              const slug = btn.dataset.slug;
              const decision = btn.dataset.decision;
              const statusEl = document.querySelector(`[data-status-for="${slug}"]`);
              // Disable all decision buttons for this card to prevent double-fires.
              const card = btn.closest('.card');
              card.querySelectorAll('button[data-decision]').forEach(b => b.disabled = true);
              statusEl.textContent = `…sending ${decision}`;
              try {
                const r = await fetch('/api/empire/decide', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ slug, decision }),
                });
                const data = await r.json();
                if (data.ok) {
                  statusEl.textContent = `✓ recorded: ${decision} @ ${new Date(data.entry.ts).toLocaleTimeString()}`;
                } else {
                  statusEl.textContent = `error: ${data.error || 'unknown'}`;
                  card.querySelectorAll('button[data-decision]').forEach(b => b.disabled = false);
                }
              } catch (e) {
                statusEl.textContent = `network error: ${e.message}`;
                card.querySelectorAll('button[data-decision]').forEach(b => b.disabled = false);
              }
            }

            async function refine(btn) {
              const slug = btn.dataset.refineSlug;
              const input = document.querySelector(`[data-refine-for="${slug}"]`);
              const note = (input && input.value || '').trim();
              const statusEl = document.querySelector(`[data-status-for="${slug}"]`);
              if (!note) { statusEl.textContent = 'enter a refine instruction first'; return; }
              const card = btn.closest('.card');
              btn.disabled = true;
              statusEl.textContent = '…sending refine';
              try {
                const r = await fetch('/api/empire/decide', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ slug, decision: 'refine', note }),
                });
                const data = await r.json();
                if (data.ok) {
                  statusEl.textContent = `✓ refine queued: "${note}" — will apply on next poll`;
                  if (input) input.value = '';
                } else {
                  statusEl.textContent = `error: ${data.error || 'unknown'}`;
                }
              } catch (e) {
                statusEl.textContent = `network error: ${e.message}`;
              } finally {
                btn.disabled = false;
              }
            }

            async function addtext(btn) {
              const slug = btn.dataset.addtextSlug;
              const q = (k) => document.querySelector(`[data-${k}="${slug}"]`);
              const text = ((q('at-text') || {}).value || '').trim();
              const statusEl = document.querySelector(`[data-status-for="${slug}"]`);
              if (!text) { if (statusEl) statusEl.textContent = 'enter text to print first'; return; }
              const spec = {
                text,
                font: (q('at-font') || {}).value || 'bold_sans',
                color: (q('at-color') || {}).value || 'white',
                placement: (q('at-place') || {}).value || 'back',
              };
              btn.disabled = true;
              if (statusEl) statusEl.textContent = '…queuing add-text';
              try {
                const r = await fetch('/api/empire/decide', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ slug, decision: 'addtext', note: JSON.stringify(spec) }),
                });
                const data = await r.json();
                if (data.ok) {
                  if (statusEl) statusEl.textContent = `✓ text "${text}" → ${spec.placement} queued — applies on next poll`;
                  const ti = q('at-text'); if (ti) ti.value = '';
                } else if (statusEl) {
                  statusEl.textContent = `error: ${data.error || 'unknown'}`;
                }
              } catch (e) {
                if (statusEl) statusEl.textContent = `network error: ${e.message}`;
              } finally {
                btn.disabled = false;
              }
            }

            // Hydrate latest decisions on page load.
            (async () => {
              try {
                const r = await fetch('/api/empire/items');
                const { items } = await r.json();
                for (const item of (items || [])) {
                  const latest = item.latest_decision;
                  if (!latest) continue;
                  const statusEl = document.querySelector(`[data-status-for="${item.slug}"]`);
                  if (statusEl) {
                    statusEl.textContent = `was: ${latest.decision} @ ${new Date(latest.ts).toLocaleString()}`;
                  }
                }
              } catch (e) {}
            })();

            // Wire all decision buttons.
            document.querySelectorAll('button[data-decision]').forEach(b => {
              b.addEventListener('click', () => decide(b));
            });
            // Wire refine buttons.
            document.querySelectorAll('button[data-refine-slug]').forEach(b => {
              b.addEventListener('click', () => refine(b));
            });
            // Wire add-text buttons.
            document.querySelectorAll('button[data-addtext-slug]').forEach(b => {
              b.addEventListener('click', () => addtext(b));
            });
          </script>
        </body></html>
        """).replace("$count", str(len(rows_html))).replace(
            "$stamp", datetime.now().strftime("%Y-%m-%d %H:%M")
        ).replace(
            "$body",
            '<div class="grid">' + "\n".join(rows_html) + "</div>" if rows_html
            else '<div class="empty">No picks yet. Run <code>empire run --brand earl_biggers --live</code>.</div>',
        )
