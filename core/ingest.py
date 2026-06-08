"""Drop-folder ingestion → default merch bundle.

Drop an image and/or a prompt file into the inbox, and this fans it out into
the default bundle (tee in 7 colors, 15oz mug, 4" sticker, 11x14 poster) as
Printify drafts, builds preview mockups, and records each as a Listing in the
store so the existing mc-publish / mc-poll approval loop can carry it to .206
and on to Printify → Etsy.

Drop conventions (files pair by stem inside the inbox):
  myidea.png                 → image is the print art (prompt-less)
  myidea.txt                 → prompt only (art generated from text)
  myidea.png + myidea.txt    → image is the art, text seeds title/description

Image extensions: .png .jpg .jpeg .webp   Prompt extensions: .txt .md .prompt
After processing, source files move to inbox/processed/<stamp>/.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import bundle as bundle_mod
from . import designs as designs_mod
from . import images as images_mod
from . import printify as printify_mod
from . import util
from .models import Concept, Design, Listing
from .store import Store

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
PROMPT_EXTS = {".txt", ".md", ".prompt"}
# Sidecar written by the local upload UI: JSON carrying the optional prompt plus
# the back/under stamp spec (text, font, color, placement). Paired by stem, e.g.
# "myidea.png" + "myidea.empirespec.json".
SPEC_SUFFIX = ".empirespec.json"

# Drops whose stem/prompt mention one of these get circle-cropped to a sphere
# (no square edges) before upload. Override with EMPIRE_CIRCULAR_DROP=1 (force on
# for every drop) or =0 (force off).
_CIRCULAR_KEYWORDS = ("local81", "logo", "sphere", "badge", "roundel")


def _wants_circular(stem: str, prompt: str) -> bool:
    flag = os.getenv("EMPIRE_CIRCULAR_DROP", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    hay = f"{stem} {prompt}".lower()
    return any(k in hay for k in _CIRCULAR_KEYWORDS)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ART_DIR = DATA_DIR / "art"
ART_DIR.mkdir(parents=True, exist_ok=True)


def inbox_path() -> Path:
    p = Path(os.getenv("EMPIRE_INBOX", str(Path(__file__).resolve().parents[1] / "inbox")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "drop"


def discover(inbox: Optional[Path] = None) -> List[Dict]:
    """Group inbox files into drop jobs keyed by stem.

    Returns list of {stem, image, prompt_file} (paths may be None).
    Skips the processed/ subdir.
    """
    inbox = inbox or inbox_path()
    jobs: Dict[str, Dict] = {}

    def _job(stem: str) -> Dict:
        return jobs.setdefault(
            stem, {"stem": stem, "image": None, "prompt_file": None, "spec_file": None})

    for f in sorted(inbox.iterdir()):
        if f.is_dir() or f.name.startswith("."):
            continue
        if f.name.endswith(SPEC_SUFFIX):
            _job(f.name[: -len(SPEC_SUFFIX)])["spec_file"] = f
            continue
        ext = f.suffix.lower()
        if ext in IMAGE_EXTS:
            _job(f.stem)["image"] = f
        elif ext in PROMPT_EXTS:
            _job(f.stem)["prompt_file"] = f
    return list(jobs.values())


def _is_stable(paths: List[Path], settle: float = 1.5) -> bool:
    """True if none of the files changed size across a short settle window."""
    sizes = {p: p.stat().st_size for p in paths if p and p.exists()}
    time.sleep(settle)
    for p, sz in sizes.items():
        if not p.exists() or p.stat().st_size != sz:
            return False
    return True


def _art_for_drop(job: Dict, title: str, prompt: str, *, backend: Optional[str],
                  dry_run: bool) -> Tuple[bytes, str]:
    """Return (art_bytes, source).

    Dropped image + prompt: the prompt EDITS the image (img2img) when an edit
    backend is configured, so the .txt enhancements actually change the art.
    Falls safe to the image as-is if no edit backend or the edit fails.
    No image: generate from the prompt (text-to-image).
    """
    img = job.get("image")
    if img and img.exists():
        raw = img.read_bytes()
        instruction = (prompt or "").strip()
        if instruction:
            edit_backend = images_mod.select_edit_backend()
            if edit_backend:
                edited, src = images_mod.edit_design_png(raw, instruction,
                                                         backend=backend, dry_run=dry_run)
                if edited is not None:
                    return edited, f"drop-image-edited:{img.name} ({src})"
                # edit attempted but failed → keep original art, note it
                return raw, f"drop-image:{img.name} (edit failed: {src})"
        return raw, f"drop-image:{img.name}"
    variants, src = images_mod.generate_design_variants(
        title or prompt[:40] or "design", prompt or title,
        backend=backend, dry_run=dry_run,
    )
    return variants[0], src


_PLACEHOLDER_NAME = "_placeholder.png"
# Products whose tee logic should pull several front color mockups (one per color).
_MULTI_MOCKUP_KEYS = {"tee", "tiedye"}


def _placeholder_path() -> Path:
    """A neutral 'mockup rendering…' tile shown until Printify renders arrive.

    Generated once and reused by every pending card (local mockup compositing is
    intentionally disabled — Printify's own renders are the source of truth).
    """
    p = designs_mod.MOCKUP_DIR / _PLACEHOLDER_NAME
    if p.exists():
        return p
    if designs_mod._PIL_AVAILABLE:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (900, 900), (20, 21, 26))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([60, 60, 840, 840], radius=28, outline=(70, 74, 88), width=3)
        msg = "Printify mockup\nrendering…"
        try:
            d.multiline_text((450, 450), msg, fill=(150, 160, 185),
                             anchor="mm", align="center", spacing=14)
        except TypeError:  # very old PIL without anchor
            d.multiline_text((360, 420), msg, fill=(150, 160, 185), align="center")
        img.save(p, format="PNG")
    else:
        p.write_bytes(b"")
    return p


def is_placeholder(path: Optional[str]) -> bool:
    return bool(path) and str(path).endswith(_PLACEHOLDER_NAME)


def _download(url: str, dest: Path) -> None:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "tee-empire/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        dest.write_bytes(r.read())


def _printify_mockups(client, product_id: str, product_key: str, slug_fs: str,
                      brand_slug: str, *, tee_count: int = 3,
                      include_positions: Optional[set] = None,
                      tries: int = 6, delay: float = 2.0) -> Tuple[Optional[str], List[str]]:
    """Download Printify's *own* rendered mockups for a freshly-created draft.

    Printify renders flawless product mockups server-side; we mirror those into
    empire-picks instead of compositing locally. Tee → up to ``tee_count`` front
    color mockups (one per color), every other product → its single front mockup.

    ``include_positions`` (e.g. ``{"back"}``) appends the default mockup for each
    of those extra print positions — used so a tee with text added on the BACK
    carries its back image through to empire-picks and on to Etsy at publish time.
    When set, polling also waits until at least one image for those positions has
    rendered (the back mockup only appears after the back print is attached).

    Mockups render asynchronously, so we poll ``get_product`` until images appear.
    Returns (primary_path, all_paths); (None, []) if nothing could be fetched.
    """
    include_positions = {p.lower() for p in (include_positions or set())}
    images: List[Dict] = []
    for _ in range(tries):
        try:
            product = client.get_product(product_id)
        except Exception:
            time.sleep(delay)
            continue
        images = product.get("images") or []
        have_extra = (not include_positions or
                      any(im.get("position") in include_positions for im in images))
        if images and have_extra:
            break
        time.sleep(delay)
    fronts = [im for im in images if im.get("position") == "front" and im.get("src")]
    if not fronts:
        fronts = [im for im in images if im.get("src")]
    if not fronts:
        return None, []
    if product_key in _MULTI_MOCKUP_KEYS:
        chosen, seen = [], set()
        for im in fronts:
            vids = tuple(im.get("variant_ids") or [])
            if vids in seen:
                continue
            seen.add(vids)
            chosen.append(im)
            if len(chosen) >= tee_count:
                break
    else:
        default = [im for im in fronts if im.get("is_default")]
        chosen = (default or fronts)[:1]
    # (tag, image) pairs → tag becomes the filename suffix so back ≠ front.
    targets: List[Tuple[str, Dict]] = [(f"pf{i}", im) for i, im in enumerate(chosen)]
    for pos in sorted(include_positions):
        cands = [im for im in images if im.get("position") == pos and im.get("src")]
        if not cands:
            continue
        default = [im for im in cands if im.get("is_default")]
        targets.append((pos, (default or cands)[0]))
    paths: List[str] = []
    for tag, im in targets:
        dest = designs_mod.MOCKUP_DIR / f"{brand_slug}__{slug_fs}__{product_key}-{tag}.jpg"
        try:
            _download(im["src"], dest)
            paths.append(str(dest))
        except Exception:
            continue
    return (paths[0] if paths else None), paths


def process_drop(job: Dict, *, brand_slug: str = "earl_biggers", dry_run: bool = True,
                 backend: Optional[str] = None, store: Optional[Store] = None) -> Dict:
    """Fan one drop out into the full bundle of Printify drafts + store rows."""
    store = store or Store()
    stem = job["stem"]
    prompt = ""
    if job.get("prompt_file") and job["prompt_file"].exists():
        prompt = job["prompt_file"].read_text(encoding="utf-8", errors="replace").strip()

    # Optional upload-UI sidecar: seeds the prompt (if no .txt) and supplies a
    # back/under text stamp applied to apparel drafts in this same render.
    text_spec: Optional[Dict] = None
    sf = job.get("spec_file")
    if sf and sf.exists():
        try:
            spec_raw = json.loads(sf.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            spec_raw = {}
        if not prompt and (spec_raw.get("prompt") or "").strip():
            prompt = spec_raw["prompt"].strip()
        stamp_text = (spec_raw.get("text") or "").strip()
        if stamp_text:
            text_spec = {
                "text": stamp_text,
                "font": spec_raw.get("font") or "bold_sans",
                "color": spec_raw.get("color") or "white",
                "placement": spec_raw.get("placement") or "back",
            }

    title_seed = (prompt.splitlines()[0] if prompt else stem.replace("-", " ").replace("_", " ")).strip()
    title_seed = title_seed[:80] or stem
    base_slug = f"{_slugify(title_seed)}-{datetime.now().strftime('%m%d%H%M%S')}"
    slug_fs = base_slug  # filesystem-safe (already slugified)

    art_bytes, art_src = _art_for_drop(job, title_seed, prompt, backend=backend, dry_run=dry_run)
    if _wants_circular(stem, prompt):
        art_bytes = designs_mod.circular_trim(art_bytes)
        art_src += " +sphere"
    art_path = ART_DIR / f"{base_slug}.png"
    art_path.write_bytes(art_bytes)

    client = printify_mod.PrintifyClient(shop_id=os.getenv("PRINTIFY_SHOP_ID"))
    results: List[Dict] = []
    for spec in bundle_mod.BUNDLE:
        key = spec["key"]
        comp_slug = f"{base_slug}::{key}"
        prod_title = util.sanitize_for_marketplace(f"{title_seed} {spec['title_suffix']}")
        description = util.sanitize_for_marketplace(
            (f"{prompt}\n\n" if prompt else "") + spec["description"]
        )
        try:
            upload = client.upload_image(f"{base_slug}-{key}.png", art_bytes, dry_run=dry_run)
            image_id = upload.get("id") or f"dryrun-{key}"
            created = client.create_product(
                title=prod_title, description=description,
                blueprint_id=spec["blueprint_id"], variant_ids=spec["variant_ids"],
                image_id=image_id, print_provider_id=spec["print_provider_id"],
                tags=[], price_cents=spec["price_cents"], dry_run=dry_run,
                image_transform=spec.get("image_transform"),
            )
            external_id = str(created.get("id") or f"dryrun-{comp_slug}")
            state = "pending_review"
        except Exception as exc:  # keep going; surface failure as a row
            external_id = f"error-{comp_slug}-{int(time.time())}"
            created = {"error": str(exc)}
            state = "error"

        # Local mockup compositing is disabled — every card starts on a Printify
        # placeholder and gets filled in by the poll_mockups() loop once Printify
        # finishes rendering the real server-side mockup.
        primary = str(_placeholder_path())
        mock_paths = [primary]

        # Concept + Design + Listing rows (composite slug per product).
        concept = Concept(
            brand=brand_slug, lane="drops", slug=comp_slug, input_handle=stem,
            product_title=f"{title_seed} · {spec['label']}", tagline=title_seed,
            design_prompt=prompt or title_seed,
            suggested_colors=(bundle_mod.TEE_COLOR_LABELS if key == "tee"
                              else bundle_mod.TIEDYE_COLOR_LABELS if key == "tiedye" else []),
            tags=[], safety_notes=[], source="drop",
            extra={"product": key, "art_path": str(art_path)},
        )
        store.upsert_concept(concept)
        design = Design(
            concept_slug=comp_slug, brand=brand_slug, design_text=title_seed,
            shirt_color="black", text_color="white", font_style="mono",
            design_notes=f"{(prompt or title_seed)[:200]}\n\n[judge] drop bundle ({art_src})",
            mockup_path=primary, source=f"drop:{art_src}:{key}",
            ocr_score=1.0, variant_count=len(mock_paths), variant_paths=mock_paths,
        )
        store.upsert_design(design)
        listing = Listing(
            brand=brand_slug, concept_slug=comp_slug, platform="printify",
            external_id=external_id, state=state, title=prod_title, description=description,
            price_cents=spec["price_cents"],
            extra={"product": key, "product_label": spec["label"],
                   "blueprint_id": spec["blueprint_id"],
                   "print_provider_id": spec["print_provider_id"],
                   "variant_ids": spec["variant_ids"], "art_path": str(art_path),
                   "prompt": prompt, "image_id": image_id if state != "error" else None,
                   "create_response": created},
        )
        store.upsert_listing(listing)

        # Stamp the back/under text from the upload sidecar in this same render.
        # Only apparel (tee/tiedye) carries the back/sleeve/neck/underneath
        # placements; mug/sticker/poster have no such print area.
        stamp_result = None
        if (text_spec and state != "error" and not dry_run
                and key in _MULTI_MOCKUP_KEYS):
            try:
                stamp_result = add_text_to_listing(
                    listing, text_spec, dry_run=dry_run, store=store)
            except Exception as exc:  # never let one stamp abort the drop
                stamp_result = {"addtext": "error", "error": str(exc)}

        row = {"product": key, "slug": comp_slug, "external_id": external_id,
               "state": state, "mockup": primary}
        if stamp_result is not None:
            row["text_stamp"] = stamp_result
        results.append(row)

    return {"drop": base_slug, "title": title_seed, "art_source": art_src,
            "dry_run": dry_run, "products": results,
            "tie_dye_note": bundle_mod.TIE_DYE_NOTE}


def archive_job(job: Dict) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = inbox_path() / "processed" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for k in ("image", "prompt_file", "spec_file"):
        f = job.get(k)
        if f and f.exists():
            f.rename(dest / f.name)


def poll_mockups(brand_slug: str, *, store: Optional[Store] = None,
                 interval: int = 30, total: int = 300) -> Dict:
    """Poll Printify every ``interval`` s for up to ``total`` s, swapping each
    card's placeholder for the real server-rendered mockup as it becomes ready.

    Republishes empire-picks after every round that fills in at least one card,
    so the board visibly fills in. Returns counts. Skips dry-run/errored rows.
    """
    store = store or Store()
    from . import mission_control
    client = printify_mod.PrintifyClient(shop_id=os.getenv("PRINTIFY_SHOP_ID"))
    deadline = time.time() + total
    filled_total = 0
    pending: List = []
    while True:
        pending = []
        for l in store.list_listings(brand=brand_slug):
            if l.platform != "printify" or l.state == "error":
                continue
            if str(l.external_id).startswith(("dryrun", "error")):
                continue
            d = store.get_design(l.brand, l.concept_slug)
            if d and is_placeholder(d.mockup_path):
                pending.append((l, d))
        if not pending:
            break
        filled = 0
        for l, d in pending:
            key = (l.extra or {}).get("product", "tee")
            base = l.concept_slug.split("::")[0]
            primary, paths = _printify_mockups(client, l.external_id, key, base,
                                               l.brand, tries=1, delay=0)
            if paths:
                d.mockup_path = primary
                d.variant_paths = paths
                store.upsert_design(d)
                filled += 1
        if filled:
            filled_total += filled
            mission_control.publish_picks(brand_filter=brand_slug, limit=60)
        if time.time() >= deadline:
            break
        time.sleep(interval)
    return {"mockups_filled": filled_total, "still_pending": len(pending)}


def run_once(*, brand_slug: str = "earl_biggers", dry_run: bool = True,
             backend: Optional[str] = None, publish: bool = True,
             store: Optional[Store] = None) -> Dict:
    """Process every pending drop in the inbox, then (optionally) push to .206."""
    store = store or Store()
    jobs = discover()
    processed = []
    for job in jobs:
        files = [job.get("image"), job.get("prompt_file")]
        if not _is_stable([f for f in files if f]):
            continue  # still being written; pick it up next pass
        res = process_drop(job, brand_slug=brand_slug, dry_run=dry_run,
                           backend=backend, store=store)
        archive_job(job)
        processed.append(res)
    out = {"processed": len(processed), "drops": processed}
    if processed and publish:
        from . import mission_control
        # Show placeholder cards immediately, then fill them in from Printify.
        out["publish"] = mission_control.publish_picks(brand_filter=brand_slug, limit=60)
        if not dry_run:
            out["mockups"] = poll_mockups(brand_slug, store=store)
    return out


def watch(*, brand_slug: str = "earl_biggers", dry_run: bool = True,
          backend: Optional[str] = None, interval: int = 10,
          publish: bool = True) -> None:
    """Poll the inbox forever; process new drops as they land."""
    inbox = inbox_path()
    print(json.dumps({"watching": str(inbox), "interval_s": interval,
                      "dry_run": dry_run, "brand": brand_slug}), flush=True)
    store = Store()
    while True:
        try:
            res = run_once(brand_slug=brand_slug, dry_run=dry_run, backend=backend,
                          publish=publish, store=store)
            if res["processed"]:
                print(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), **res},
                                 default=str), flush=True)
        except Exception as exc:  # never let the watcher die on one bad drop
            print(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                              "error": str(exc)}), flush=True)
        time.sleep(interval)


def regenerate_art(listing: Listing, note: str, *, dry_run: bool = True,
                   backend: Optional[str] = None, store: Optional[Store] = None) -> Dict:
    """Apply a reviewer 'refine' note: regenerate/annotate art, update the Printify
    draft image, and rebuild the preview mockup. Used by `mc-poll` for `refine`.
    """
    store = store or Store()
    ex = listing.extra or {}
    key = ex.get("product", "tee")
    art_path = ex.get("art_path")
    prompt = ex.get("prompt", "")
    base = ex.get("art_path") and Path(art_path).stem or listing.concept_slug.split("::")[0]
    old_art = Path(art_path).read_bytes() if art_path and Path(art_path).exists() else None

    # Decide how to produce the new art.
    #  - If we have the source art + an edit backend: do an instruction-based
    #    EDIT (preserves the original, applies the reviewer's changes). If that
    #    backend errors, FAIL loudly — never silently regenerate over their art.
    #  - If we have source art but no edit backend: deterministic text overlay.
    #  - If there's no source art (pure-prompt drop): generate fresh from prompt+note.
    new_art: Optional[bytes] = None
    src = ""
    edit_backend = images_mod.select_edit_backend()
    if old_art is not None and edit_backend:
        edited, src = images_mod.edit_design_png(old_art, note, backend=backend, dry_run=dry_run)
        if edited is None:
            return {"slug": listing.concept_slug, "refine": "error",
                    "error": f"image edit failed ({src}); original art left unchanged"}
        new_art = edited
    elif old_art is not None:
        new_art = designs_mod.overlay_text_panel(old_art, text=note)
        src = "overlay (no edit backend; set OPENAI_API_KEY for full edits)"
    else:
        combined = (prompt + "\n" + note).strip() if prompt else note
        if combined:
            try:
                variants, src = images_mod.generate_design_variants(
                    note[:40] or "refine", combined, backend=backend, dry_run=dry_run)
                new_art = variants[0]
            except Exception as exc:
                return {"slug": listing.concept_slug, "refine": "error", "error": str(exc)}
    if new_art is None:
        return {"slug": listing.concept_slug, "refine": "skipped", "reason": "no art source"}

    # Persist new art, update Printify draft image, rebuild mockup.
    if art_path:
        Path(art_path).write_bytes(new_art)
    client = printify_mod.PrintifyClient(shop_id=os.getenv("PRINTIFY_SHOP_ID"))
    upload = client.upload_image(f"{base}-{key}-refine.png", new_art, dry_run=dry_run)
    image_id = upload.get("id") or ex.get("image_id")
    # Reuse the draft's existing print_areas (carries the full variant set) and
    # only swap the image — a hand-built print_areas with our enabled-only
    # variant subset is rejected by Printify (error 8251).
    try:
        client.replace_print_image(listing.external_id, image_id, dry_run=dry_run)
    except Exception as exc:
        return {"slug": listing.concept_slug, "refine": "error", "error": str(exc)}

    slug_fs = base
    primary = mock_paths = None
    if not dry_run and not str(listing.external_id).startswith(("dryrun", "error")):
        primary, mock_paths = _printify_mockups(client, listing.external_id, key,
                                                slug_fs, listing.brand)
    if not mock_paths:  # render not ready yet → placeholder; poll_mockups will fill in
        primary = str(_placeholder_path())
        mock_paths = [primary]
    design = store.get_design(listing.brand, listing.concept_slug)
    if design:
        design.mockup_path = primary
        design.variant_paths = mock_paths
        design.design_notes = f"refine: {note[:120]}\n\n[judge] refined ({src})"
        store.upsert_design(design)
    ex["image_id"] = image_id
    listing.extra = ex
    listing.state = "pending_review"
    store.upsert_listing(listing)
    return {"slug": listing.concept_slug, "refine": "applied", "art_source": src,
            "mockup": primary}


# Reviewer-chosen placement → Printify placeholder + transform + text canvas.
# "underneath" stacks text low within the existing front area (keeps the art);
# everything else is a distinct placeholder the blueprint must support.
_TEXT_PLACEMENTS = {
    "back":         {"position": "back",         "x": 0.5, "y": 0.5,  "scale": 0.9, "stack": False, "canvas": (1600, 2000)},
    "left_sleeve":  {"position": "left_sleeve",  "x": 0.5, "y": 0.5,  "scale": 0.9, "stack": False, "canvas": (1200, 500)},
    "right_sleeve": {"position": "right_sleeve", "x": 0.5, "y": 0.5,  "scale": 0.9, "stack": False, "canvas": (1200, 500)},
    "neck":         {"position": "neck",         "x": 0.5, "y": 0.5,  "scale": 0.8, "stack": False, "canvas": (1200, 400)},
    "underneath":   {"position": "front",        "x": 0.5, "y": 0.84, "scale": 0.5, "stack": True,  "canvas": (1600, 600)},
}


def add_text_to_listing(listing: Listing, spec: Dict, *, dry_run: bool = True,
                        store: Optional[Store] = None) -> Dict:
    """Stamp literal text onto a print placement of an existing Printify draft.

    ``spec`` = {text, font, color, placement}. Renders the exact words as a
    transparent PNG (no AI reinterpretation), uploads it, and attaches it to the
    chosen placeholder while preserving the draft's full variant set. Used by
    ``mc-poll`` for the ``addtext`` decision.
    """
    store = store or Store()
    text = (spec.get("text") or "").strip()
    if not text:
        return {"slug": listing.concept_slug, "addtext": "skipped", "reason": "no text"}
    placement = spec.get("placement", "back")
    plc = _TEXT_PLACEMENTS.get(placement)
    if not plc:
        return {"slug": listing.concept_slug, "addtext": "error",
                "error": f"unknown placement '{placement}'"}
    font_key = spec.get("font", "bold_sans")
    color = spec.get("color", "white")
    ex = listing.extra or {}
    key = ex.get("product", "tee")
    base = listing.concept_slug.split("::")[0]

    try:
        text_png = designs_mod.render_text_png(
            text, font_key=font_key, color=color, canvas=plc["canvas"],
            outline=(color in ("white", "gold", "grey")))
    except Exception as exc:
        return {"slug": listing.concept_slug, "addtext": "error",
                "error": f"text render failed: {exc}"}

    client = printify_mod.PrintifyClient(shop_id=os.getenv("PRINTIFY_SHOP_ID"))
    upload = client.upload_image(f"{base}-{key}-{placement}-text.png", text_png, dry_run=dry_run)
    image_id = upload.get("id") or (f"dry-{placement}" if dry_run else None)
    if not image_id:
        return {"slug": listing.concept_slug, "addtext": "error",
                "error": "upload returned no image id"}
    try:
        client.add_text_placement(listing.external_id, image_id, plc["position"],
                                  x=plc["x"], y=plc["y"], scale=plc["scale"],
                                  stack=plc["stack"], dry_run=dry_run)
    except Exception as exc:
        return {"slug": listing.concept_slug, "addtext": "error", "error": str(exc)}

    ex.setdefault("added_texts", []).append(
        {"text": text, "font": font_key, "color": color, "placement": placement})
    listing.extra = ex
    listing.state = "pending_review"
    store.upsert_listing(listing)

    # Re-pull Printify's freshly re-rendered mockup so empire-picks shows how the
    # added text actually looks on the product (not a local approximation). When
    # the text lands on the BACK of a tee we first shrink the listing to a single
    # colorway (TWO_SIDED_COLORS): Printify only generates back / model / folded
    # mockups for single-color tee listings — a multi-color listing gets one front
    # per color and no back at all. The reduced listing's full mockup set then
    # syncs to Etsy for free on publish (publish_product sends images=True).
    back_included = False
    reduced_to = None
    is_back_tee = plc["position"] == "back" and key in _MULTI_MOCKUP_KEYS
    if not dry_run and not str(listing.external_id).startswith(("dryrun", "error")):
        slug_fs = base
        if is_back_tee:
            try:
                ids = bundle_mod.two_sided_variant_ids(key)
                if ids:
                    client.set_enabled_variants(listing.external_id, ids)
                    reduced_to = bundle_mod.two_sided_color_labels(key)
            except Exception as exc:
                reduced_to = f"error: {exc}"
        inc = {"back"} if plc["position"] == "back" else None
        # Reducing colors triggers a fresh render; give the back mockup time to
        # appear (it only exists after the single-color regen) before pulling.
        tries, delay = (15, 6.0) if is_back_tee else (6, 2.0)
        primary, mock_paths = _printify_mockups(client, listing.external_id, key,
                                                slug_fs, listing.brand,
                                                include_positions=inc,
                                                tries=tries, delay=delay)
        if mock_paths:
            back_included = any("-back.jpg" in p for p in mock_paths)
            design = store.get_design(listing.brand, listing.concept_slug)
            if design:
                design.mockup_path = primary
                design.variant_paths = mock_paths
                store.upsert_design(design)

    # Confirm the back mockup will actually reach Etsy: publish_product sends
    # images=True, and Printify publishes images flagged is_selected_for_publishing.
    back_on_etsy = None
    if back_included:
        try:
            prod = client.get_product(listing.external_id)
            backs = [im for im in (prod.get("images") or [])
                     if im.get("position") == "back"]
            back_on_etsy = any(im.get("is_selected_for_publishing") for im in backs)
        except Exception:
            back_on_etsy = None

    return {"slug": listing.concept_slug, "addtext": "applied", "placement": placement,
            "position": plc["position"], "text": text[:60],
            "reduced_to_colors": reduced_to,
            "back_image_included": back_included, "back_selected_for_etsy": back_on_etsy}
