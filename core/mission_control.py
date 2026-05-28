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
    for brand_slug, concept, design, listing in designs:
        slug = concept.slug
        am = asset_map.get(slug, {})
        primary = am.get("primary", "")
        variants = am.get("variants", [])
        listing_link = listing.url or ""
        listing_state = listing.state
        score_pct = int(round((design.ocr_score or 0) * 100))
        rationale = ""
        if design.design_notes and "[judge]" in design.design_notes:
            rationale = design.design_notes.split("[judge]", 1)[1].strip()
        # Build alternate thumbnails inline (clickable to swap primary).
        alts_inline = ""
        if len(variants) > 1:
            thumbs = []
            for i, vname in enumerate(variants):
                if vname == primary:
                    continue
                # Map filename → swap_v1/2/3 decision based on suffix.
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
            alts_inline = '<div class="alts-grid">' + "".join(thumbs) + "</div>"
        rows_html.append(textwrap.dedent(f"""\
            <article class="card" data-slug="{html.escape(slug)}">
              <a href="{html.escape(primary)}" target="_blank" class="thumb-link">
                <img class="thumb" src="{html.escape(primary)}" alt="{html.escape(concept.product_title)}">
              </a>
              <div class="meta">
                <h3>{html.escape(concept.product_title)}</h3>
                <p class="brand">{html.escape(brand_slug)} · {html.escape(concept.lane)} · {html.escape(listing_state)}</p>
                <p class="tagline">{html.escape(concept.tagline)}</p>
                <p class="judge">judge: {score_pct}% · {html.escape(rationale or '—')}</p>
                <div class="row decide-row">
                  <button class="btn primary" data-decision="approve" data-slug="{html.escape(slug)}">✅ APPROVE</button>
                  <button class="btn reject" data-decision="reject" data-slug="{html.escape(slug)}">❌ REJECT</button>
                </div>
                <p class="status-line" data-status-for="{html.escape(slug)}"></p>
                {alts_inline}
                <div class="row footer-row">
                  <a class="btn" href="{html.escape(primary)}" target="_blank">Open full</a>
                  {f'<a class="btn" href="{html.escape(listing_link)}" target="_blank">Printify</a>' if listing_link else ''}
                </div>
              </div>
            </article>
        """))

    return textwrap.dedent("""\
        <!DOCTYPE html>
        <html lang="en"><head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Empire — Best Picks</title>
          <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                   background: #0a0a0a; color: #eee; padding: 32px; }
            header { display: flex; align-items: baseline; justify-content: space-between;
                     margin-bottom: 24px; padding-bottom: 16px;
                     border-bottom: 1px solid rgba(255,255,255,.08); }
            h1 { font-size: 22px; letter-spacing: -.5px; }
            .meta-stamp { font-size: 12px; opacity: .5; }
            .grid { display: grid; gap: 24px;
                    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); }
            .card { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08);
                    border-radius: 16px; overflow: hidden;
                    transition: transform .15s ease, border-color .15s ease; }
            .card:hover { transform: translateY(-2px); border-color: rgba(255,255,255,.2); }
            .thumb-link { display: block; background: #1a1a1a; }
            .thumb { width: 100%; height: 320px; object-fit: contain; display: block; }
            .meta { padding: 16px 18px 18px; }
            .meta h3 { font-size: 15px; margin-bottom: 4px; font-weight: 600; }
            .brand { font-size: 11px; opacity: .55; text-transform: uppercase;
                     letter-spacing: .8px; margin-bottom: 8px; }
            .tagline { font-size: 13px; opacity: .8; margin-bottom: 10px; line-height: 1.4; }
            .judge { font-size: 12px; opacity: .65; line-height: 1.4; margin-bottom: 10px;
                     font-style: italic; }
            .alts { font-size: 12px; opacity: .6; margin-bottom: 10px; }
            .alt { color: #6cf; text-decoration: none; margin-right: 4px; }
            .alt:hover { text-decoration: underline; }
            .row { display: flex; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
            .decide-row { margin: 8px 0 4px; }
            .footer-row { margin-top: 12px; padding-top: 10px;
                          border-top: 1px solid rgba(255,255,255,.06); }
            .btn { display: inline-block; padding: 8px 14px; font-size: 12px;
                   border-radius: 8px; text-decoration: none; color: #ccc;
                   background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.1);
                   cursor: pointer; font-family: inherit; }
            .btn.primary { color: #0a0a0a; background: #6cf; border-color: #6cf; }
            .btn.reject { color: #f88; border-color: rgba(255,100,100,.3); }
            .btn:hover { background: rgba(255,255,255,.12); }
            .btn.primary:hover { background: #8df; }
            .btn.reject:hover { background: rgba(255,100,100,.15); }
            .btn:disabled { opacity: .4; cursor: not-allowed; }
            .status-line { font-size: 12px; min-height: 16px; margin: 6px 0;
                           color: #6cf; font-weight: 500; }
            .alts-grid { display: grid; grid-template-columns: repeat(3, 1fr);
                         gap: 8px; margin-top: 10px; }
            .alt-cell { display: flex; flex-direction: column; gap: 4px; align-items: center; }
            .alt-thumb { width: 100%; height: 80px; object-fit: contain;
                         background: #1a1a1a; border-radius: 6px;
                         border: 1px solid rgba(255,255,255,.08); display: block; }
            .alt-pick { font-size: 10px; padding: 4px 6px; background: rgba(255,255,255,.05);
                        color: #ccc; border: 1px solid rgba(255,255,255,.1);
                        border-radius: 5px; cursor: pointer; width: 100%;
                        font-family: inherit; }
            .alt-pick:hover { background: rgba(108,200,255,.15); color: #6cf; }
            .empty { text-align: center; opacity: .5; padding: 60px; }
          </style>
        </head>
        <body>
          <header>
            <h1>TeeEmpire · Best Picks</h1>
            <span class="meta-stamp">$count items · refreshed $stamp</span>
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
          </script>
        </body></html>
        """).replace("$count", str(len(rows_html))).replace(
            "$stamp", datetime.now().strftime("%Y-%m-%d %H:%M")
        ).replace(
            "$body",
            '<div class="grid">' + "\n".join(rows_html) + "</div>" if rows_html
            else '<div class="empty">No picks yet. Run <code>empire run --brand earl_biggers --live</code>.</div>',
        )
