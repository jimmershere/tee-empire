#!/usr/bin/env python3
"""Portwright Press CLI — `python -m empire.cli <command> ...`.

The `empire` CLI command name and `EMPIRE_*` env prefix are intentionally
unchanged (renaming them is high-blast-radius; deferred).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

# Allow `python /app/tee-empire/cli.py ...` as well as `-m empire.cli`.
# Also support flat layout (tee-empire/ with core/ at root) by making the root
# importable as the "empire" package without requiring an on-disk "empire/" subdir.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Make "import empire.core" work when running from the source root directly
# (common for local dev / flat layout with core/ at the repo root, no "empire/" subdir).
# We create a proper namespace package so subpackage imports (empire.core.xxx) succeed.
import types as _types
import importlib.util as _importlib_util
if "empire" not in sys.modules:
    _emp = _types.ModuleType("empire")
    _emp.__path__ = [str(ROOT)]
    # Mark as package so "from empire.core import ..." traverses it
    _emp.__package__ = "empire"
    sys.modules["empire"] = _emp
    # Also ensure "empire.core" and "empire.core.xxx" can be found by adding a finder
    # that resolves empire.core -> ROOT/core
    class _EmpireCoreFinder:
        @staticmethod
        def find_spec(fullname, path, target=None):
            if fullname == "empire.core" or fullname.startswith("empire.core."):
                # Map empire.core.foo -> ROOT/core/foo.py (or package)
                rel = fullname[len("empire."):]  # "core" or "core.foo"
                candidate = ROOT / rel.replace(".", "/")
                if candidate.is_dir():
                    init = candidate / "__init__.py"
                    if init.exists():
                        spec = _importlib_util.spec_from_file_location(fullname, str(init))
                        if spec:
                            spec.submodule_search_locations = [str(candidate)]
                            return spec
                else:
                    py = candidate.with_suffix(".py")
                    if py.exists():
                        return _importlib_util.spec_from_file_location(fullname, str(py))
            return None
    sys.meta_path.append(_EmpireCoreFinder)  # type: ignore[arg-type]

# Auto-load empire/.env into os.environ so subcommands see the keys.
def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    import os as _os
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        v = v.split("#", 1)[0].strip().strip('"').strip("'")
        _os.environ.setdefault(k.strip(), v)


_load_env_file(Path(__file__).resolve().parent / ".env")

from empire.core import analytics, brands as brands_mod, fixtures, hitl as hitl_mod  # noqa: E402
from empire.core.orchestrator import Orchestrator  # noqa: E402
from empire.core.store import Store  # noqa: E402


def cmd_brands(args: argparse.Namespace) -> int:
    for slug in brands_mod.list_brand_slugs():
        brand = brands_mod.load_brand(slug)
        lanes = ", ".join(brand.lanes) or "(none)"
        print(f"{slug:18s}  {brand.name:18s}  lanes: {lanes}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    store = Store()
    src = Path(args.source).expanduser().resolve()
    if not src.exists():
        print(f"Source not found: {src}", file=sys.stderr)
        return 2
    c, d = fixtures.import_earl_biggers_from_path(src, store)
    print(json.dumps({"imported_concepts": c, "imported_designs": d}, indent=2))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    brand = brands_mod.load_brand(args.brand)
    orch = Orchestrator(dry_run=not args.live)
    concepts = orch.plan(brand, lanes=args.lanes or None, per_lane=args.per_lane,
                         use_api=args.use_api)
    print(json.dumps({"brand": brand.slug, "planned": [c.slug for c in concepts]}, indent=2))
    return 0


def cmd_design(args: argparse.Namespace) -> int:
    brand = brands_mod.load_brand(args.brand)
    orch = Orchestrator(dry_run=not args.live)
    designs = orch.design(brand, concept_slugs=args.concepts or None, product_type=args.product_type)
    print(json.dumps({"brand": brand.slug,
                      "designed": [{"slug": d.concept_slug, "mockup": d.mockup_path, "product_type": args.product_type or "shirt"}
                                   for d in designs]}, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    brand = brands_mod.load_brand(args.brand)
    orch = Orchestrator(dry_run=not args.live)
    out = {}
    if args.platform in {"printify", "both"}:
        out["printify"] = [l.to_dict() for l in
                           orch.list_to_printify(brand, concept_slugs=args.concepts or None, product_type=args.product_type)]
    if args.platform in {"etsy", "both"}:
        out["etsy"] = [l.to_dict() for l in
                       orch.list_to_etsy(brand, concept_slugs=args.concepts or None, product_type=args.product_type)]
    print(json.dumps(out, indent=2))
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    brand = brands_mod.load_brand(args.brand)
    orch = Orchestrator(dry_run=not args.live)
    out = orch.send_reviews(brand, concept_slugs=args.concepts or None)
    print(json.dumps(out, indent=2))
    return 0


def cmd_poll(args: argparse.Namespace) -> int:
    bot = hitl_mod.HITLBot(dry_run=not args.live)
    handled = bot.poll_once(on_approve=hitl_mod.default_approve_handler,
                            timeout=args.timeout)
    print(json.dumps({"updates_handled": handled}, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    brand = brands_mod.load_brand(args.brand)
    orch = Orchestrator(dry_run=not args.live)
    report = orch.full_run(
        brand, lanes=args.lanes or None, per_lane=args.per_lane, use_api=args.use_api,
        send_etsy=not args.skip_etsy, send_printify=not args.skip_printify,
        send_reviews=not args.skip_reviews,
        product_type=args.product_type,
    )
    print(json.dumps(report.to_dict(), indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = Store()
    summary = {
        "brands": [
            {"slug": s, **{k: v for k, v in brands_mod.load_brand(s).to_dict().items()
                           if k in {"name", "lanes"}}}
            for s in brands_mod.list_brand_slugs()
        ],
        "db_stats": store.brand_stats(),
    }
    print(json.dumps(summary, indent=2))
    return 0


def cmd_mc_publish(args: argparse.Namespace) -> int:
    from empire.core import mission_control
    out = mission_control.publish_picks(brand_filter=args.brand or None,
                                        limit=args.limit)
    print(json.dumps(out, indent=2))
    return 0


def cmd_mc_poll(args: argparse.Namespace) -> int:
    """Read decisions from Mission Control, act on each one (publish/reject)."""
    from empire.core import mission_control
    from empire.core import printify as printify_mod
    from empire.core.store import Store
    from empire.core import brands as brands_mod

    from empire.core import ingest
    store = Store()
    decisions = mission_control.fetch_decisions()
    applied = mission_control.fetch_applied()

    # Hero products eligible for auto social promo (avoids 5 posts per drop).
    promote_products = {p.strip() for p in
                        (getattr(args, "promote_products", "") or "tee,tiedye").split(",") if p.strip()}

    # --- refine pass: regenerate draft art from reviewer notes (non-terminal) ---
    refine_ledger = Path(__file__).resolve().parent / "data" / "refine_processed.json"
    try:
        processed_refines = set(json.loads(refine_ledger.read_text())) if refine_ledger.exists() else set()
    except Exception:
        processed_refines = set()

    actions: list = []
    newly_applied: list = []
    refine_errors: list = []
    refined_any = False
    for d in decisions:
        if d.get("decision") != "refine":
            continue
        slug = d.get("slug"); ts = d.get("ts", ""); note = d.get("note", "")
        key = f"{slug}|{ts}"
        if not slug or key in processed_refines:
            continue
        listings = [l for l in store.list_listings() if l.concept_slug == slug]
        if not listings:
            actions.append({"slug": slug, "decision": "refine", "skipped": "no listing"})
            processed_refines.add(key); continue
        res = ingest.regenerate_art(listings[0], note, dry_run=not args.live, store=store)
        actions.append({"slug": slug, "decision": "refine", **res})
        if res.get("refine") == "applied":
            # Only mark consumed on success; failures stay queued so a re-run
            # (after fixing the cause) retries them instead of silently dropping.
            processed_refines.add(key)
            refined_any = True
        else:
            refine_errors.append({"slug": slug, **{k: res[k] for k in ("refine", "error", "reason") if k in res}})
    if args.live:  # dry-run is a no-side-effect preview; never consume the queue
        try:
            refine_ledger.parent.mkdir(parents=True, exist_ok=True)
            refine_ledger.write_text(json.dumps(sorted(processed_refines)))
        except Exception:
            pass

    # --- add-text pass: stamp literal text onto a print placement (non-terminal) ---
    addtext_ledger = Path(__file__).resolve().parent / "data" / "addtext_processed.json"
    try:
        processed_addtext = set(json.loads(addtext_ledger.read_text())) if addtext_ledger.exists() else set()
    except Exception:
        processed_addtext = set()
    addtext_errors: list = []
    addtext_any = False
    for d in decisions:
        if d.get("decision") != "addtext":
            continue
        slug = d.get("slug"); ts = d.get("ts", ""); note = d.get("note", "")
        key = f"{slug}|{ts}"
        if not slug or key in processed_addtext:
            continue
        try:
            spec = json.loads(note) if note else {}
        except Exception:
            spec = {}
        listings = [l for l in store.list_listings() if l.concept_slug == slug]
        if not listings:
            actions.append({"slug": slug, "decision": "addtext", "skipped": "no listing"})
            processed_addtext.add(key); continue
        res = ingest.add_text_to_listing(listings[0], spec, dry_run=not args.live, store=store)
        actions.append({"slug": slug, "decision": "addtext", **res})
        if res.get("addtext") == "applied":
            processed_addtext.add(key)
            addtext_any = True
        else:
            addtext_errors.append({"slug": slug, **{k: res[k] for k in ("addtext", "error", "reason") if k in res}})
    if args.live:  # dry-run is a no-side-effect preview; never consume the queue
        try:
            addtext_ledger.parent.mkdir(parents=True, exist_ok=True)
            addtext_ledger.write_text(json.dumps(sorted(processed_addtext)))
        except Exception:
            pass

    # Latest terminal-decision-per-slug (refine/addtext/unset are non-terminal).
    latest = {}
    for d in decisions:
        slug = d.get("slug")
        if not slug or d.get("decision") in ("refine", "addtext", "unset"):
            continue
        if slug not in latest or d.get("ts", "") > latest[slug].get("ts", ""):
            latest[slug] = d

    for slug, decision_entry in latest.items():
        if slug in applied:
            continue
        decision = decision_entry.get("decision")
        # Find the most recent listing for this concept.
        listings = [l for l in store.list_listings() if l.concept_slug == slug]
        if not listings:
            actions.append({"slug": slug, "skipped": "no listing in DB"})
            continue
        listing = listings[0]  # newest first
        try:
            brand = brands_mod.load_brand(listing.brand)
        except FileNotFoundError:
            actions.append({"slug": slug, "skipped": f"brand {listing.brand} missing"})
            continue

        if decision == "approve":
            if listing.platform == "printify":
                client = printify_mod.PrintifyClient(shop_id=brand.printify_shop_id)
                try:
                    result = client.publish_product(listing.external_id,
                                                    dry_run=not args.live)
                    listing.state = "live" if args.live else "approved-dryrun"
                    store.upsert_listing(listing)
                    store.record_review(listing.brand, slug, "approved",
                                        reviewer="mc-ui")
                    action = {"slug": slug, "decision": "approve",
                              "printify_result": result}
                    # 2nd port: publish the approved design to the maddhatchery.com storefront.
                    try:
                        from empire.core import maddhatchery as mh_mod
                        _design = store.get_design(listing.brand, slug)
                        _concept = store.get_concept(listing.brand, slug)
                        if _design and _concept:
                            action["site_result"] = mh_mod.MaddhatcheryPublisher().publish_design(
                                _concept, _design, brand, dry_run=not args.live)
                    except Exception as _se:
                        action["site_error"] = str(_se)
                    if args.live and getattr(args, "promote", False):
                        action["promotion"] = _auto_promote_listing(
                            listing, store,
                            products=promote_products,
                            is_draft=not getattr(args, "promote_live", False))
                    actions.append(action)
                    newly_applied.append(slug)
                except Exception as e:
                    actions.append({"slug": slug, "decision": "approve",
                                    "error": str(e)})
            else:
                actions.append({"slug": slug, "skipped": f"unsupported platform {listing.platform}"})
        elif decision == "reject":
            listing.state = "rejected"
            store.upsert_listing(listing)
            store.record_review(listing.brand, slug, "rejected", reviewer="mc-ui")
            actions.append({"slug": slug, "decision": "reject"})
            newly_applied.append(slug)
        elif decision in ("swap_v1", "swap_v2", "swap_v3"):
            # Promote the chosen variant to primary in the DB. Doesn't re-push
            # to Printify yet — that's a follow-up (would need update_product).
            design = store.get_design(listing.brand, slug)
            if not design:
                actions.append({"slug": slug, "skipped": "no design row"})
                continue
            suffix = f"__{decision.split('_')[1]}.png"
            for vp in design.variant_paths:
                if vp.endswith(suffix):
                    design.mockup_path = vp
                    store.upsert_design(design)
                    actions.append({"slug": slug, "decision": decision,
                                    "new_primary": vp,
                                    "note": "DB updated; re-run mc-publish + manual Printify image swap to reflect on the live listing"})
                    newly_applied.append(slug)
                    break
            else:
                actions.append({"slug": slug, "decision": decision,
                                "skipped": f"variant {suffix} not found"})
        else:
            actions.append({"slug": slug, "decision": decision,
                            "skipped": "unsupported decision"})

    if newly_applied and args.live:
        mission_control.mark_applied(newly_applied)

    # Push refreshed mockups (refines / variant swaps) back up to the .206 gallery.
    republish = None
    if refined_any or addtext_any:
        try:
            republish = mission_control.publish_picks(limit=60)
        except Exception as e:
            republish = {"error": str(e)}

    print(json.dumps({"decisions_seen": len(latest),
                      "refines_applied": refined_any,
                      "refine_errors": refine_errors,
                      "addtext_applied": addtext_any,
                      "addtext_errors": addtext_errors,
                      "republish": republish,
                      "newly_applied_persisted": len(newly_applied) if args.live else 0,
                      "would_apply": len(newly_applied) if not args.live else 0,
                      "actions": actions}, indent=2))
    if refine_errors:
        print(f"\n⚠️  {len(refine_errors)} refine(s) FAILED and remain queued:", file=sys.stderr)
        for e in refine_errors:
            print(f"   - {e.get('slug')}: {e.get('error') or e.get('reason')}", file=sys.stderr)
    if addtext_errors:
        print(f"\n⚠️  {len(addtext_errors)} add-text request(s) FAILED and remain queued:", file=sys.stderr)
        for e in addtext_errors:
            print(f"   - {e.get('slug')}: {e.get('error') or e.get('reason')}", file=sys.stderr)
    return 0


def cmd_analytics(args: argparse.Namespace) -> int:
    out = {
        "overview": analytics.empire_overview(),
        "funnel": analytics.funnel_by_brand(),
        "top_sellers": analytics.top_sellers(brand=args.brand or None, limit=args.limit),
    }
    print(json.dumps(out, indent=2))
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    from empire.core import local_approval
    local_approval.run_gate(host=args.host, port=args.port, debug=args.debug)
    return 0


def cmd_ship(args: argparse.Namespace) -> int:
    """Ship all approved (but not yet live) listings for a brand. Records reviews and sets state=live."""
    from empire.core import brands as brands_mod
    from empire.core import printify as printify_mod
    from empire.core import etsy as etsy_mod
    from empire.core.store import Store
    store = Store()
    brand = brands_mod.load_brand(args.brand)
    actions = []
    for l in store.list_listings(brand=brand.slug, state="approved"):
        try:
            if l.platform == "printify":
                client = printify_mod.PrintifyClient(shop_id=brand.printify_shop_id)
                res = client.publish_product(l.external_id, dry_run=not args.live)
                l.state = "live" if args.live else "approved-dryrun"
                l.url = res.get("url") or l.url
                store.upsert_listing(l)
                store.record_review(brand.slug, l.concept_slug, "approved", reviewer="ship-cli")
                actions.append({"slug": l.concept_slug, "platform": "printify", "result": "shipped" if args.live else "dry"})
            elif l.platform == "etsy":
                client = etsy_mod.EtsyClient(shop_id=brand.etsy_shop_id)
                res = client.update_listing_state(int(l.external_id), "active", dry_run=not args.live)
                l.state = "live" if args.live else "approved-dryrun"
                store.upsert_listing(l)
                store.record_review(brand.slug, l.concept_slug, "approved", reviewer="ship-cli")
                actions.append({"slug": l.concept_slug, "platform": "etsy", "result": "shipped" if args.live else "dry"})
        except Exception as e:
            actions.append({"slug": l.concept_slug, "platform": l.platform, "error": str(e)})
    print(json.dumps({"shipped": len([a for a in actions if "error" not in a]), "actions": actions}, indent=2))
    return 0


def cmd_publish_site(args: argparse.Namespace) -> int:
    """Publish a brand's designs to the maddhatchery.com storefront (the Nickel T's page)."""
    from empire.core import brands as brands_mod
    from empire.core import maddhatchery as mh_mod
    from empire.core.store import Store
    store = Store()
    brand = brands_mod.load_brand(args.brand)
    actions = mh_mod.publish_brand_designs(
        brand, store, dry_run=not args.live, category=args.category, limit=args.limit
    )
    ok = len([a for a in actions if a.get("success")])
    print(json.dumps({"published": ok, "total": len(actions), "live": bool(args.live),
                      "target": mh_mod.MaddhatcheryPublisher().api_url, "actions": actions},
                     indent=2, default=str))
    return 0


def cmd_drop(args: argparse.Namespace) -> int:
    """Process any image/prompt files sitting in the inbox into the default bundle."""
    from empire.core import ingest
    out = ingest.run_once(brand_slug=args.brand, dry_run=not args.live,
                          backend=args.backend or None, publish=not args.no_publish)
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Watch the inbox folder and process drops as they land (blocking loop)."""
    from empire.core import ingest
    ingest.watch(brand_slug=args.brand, dry_run=not args.live, backend=args.backend or None,
                 interval=args.interval, publish=not args.no_publish)
    return 0


def _auto_promote_listing(listing, store, *, products, is_draft):
    """Best-effort cross-promo of a just-published listing's mockup to social.

    Returns a small status dict; never raises (callers fold it into actions).
    Skips anything whose product isn't in ``products`` or whose mockup is still
    the Printify placeholder (nothing worth showing yet).
    """
    from empire.core import postbridge
    product = (listing.extra or {}).get("product")
    if products and product not in products:
        return {"promote": "skipped", "reason": f"product {product} not in {sorted(products)}"}
    design = store.get_design(listing.brand, listing.concept_slug)
    image = design.mockup_path if design else None
    if not image or "_placeholder" in image or not Path(image).exists():
        return {"promote": "skipped", "reason": "no real mockup yet"}
    caption = listing.title or product or "new drop"
    link = (listing.extra or {}).get("etsy_url")
    if link:
        caption = f"{caption}\n\n{link}"
    try:
        client = postbridge.PostBridgeClient()
        if not client.configured:
            return {"promote": "skipped", "reason": "POST_BRIDGE_API_KEY unset"}
        res = client.promote_image(image, caption, is_draft=is_draft)
        return {"promote": "draft" if is_draft else "posted",
                "post_id": res.get("post_id"), "platforms": res.get("platforms")}
    except Exception as exc:
        return {"promote": "error", "error": str(exc)}


def cmd_promote(args: argparse.Namespace) -> int:
    """Cross-promote a merch mockup to social via PostBridge (draft unless --live).

    Reuses the connected ClawFirm/content-machine social accounts. By default a
    DRAFT post is created in PostBridge for review; pass --live to publish.
    """
    from empire.core import postbridge
    image = args.image
    if not image or not Path(image).exists():
        print(f"image not found: {image}", file=sys.stderr)
        return 2
    caption = args.caption or Path(image).stem.replace("-", " ").replace("_", " ")
    if args.link:
        caption = f"{caption}\n\n{args.link}"
    platforms = [p.strip() for p in args.platforms.split(",")] if args.platforms else None
    client = postbridge.PostBridgeClient()
    if not client.configured:
        print("POST_BRIDGE_API_KEY is not set in .env", file=sys.stderr)
        return 2
    out = client.promote_image(image, caption, platforms=platforms,
                               is_draft=not args.live, dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_mc_open(args: argparse.Namespace) -> int:
    """Open an SSH tunnel to the .206 Mission Control UI so it's reachable on localhost.

    The MC server binds 127.0.0.1:3333 on .206, so it isn't directly reachable over
    the LAN. This forwards a local port to it and prints the approval URL.
    """
    import os
    import subprocess
    host = os.getenv("MC_HOST", "floor2")
    key = os.getenv("MC_SSH_KEY", str(Path.home() / ".ssh" / "floor2_key"))
    local_port = args.port
    url = f"http://localhost:{local_port}/public/empire-picks/index.html"
    cmd = [
        "ssh", "-i", key,
        "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-N", "-L", f"{local_port}:127.0.0.1:3333", host,
    ]
    print(f"Opening tunnel to Mission Control via {host} …")
    print(f"  Approval UI:  {url}")
    print(f"  (leave this running; Ctrl-C to close the tunnel)")
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="empire", description="Portwright Press — multi-brand print-on-demand merch automation")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("brands", help="List configured brands")
    sp.set_defaults(func=cmd_brands)

    sp = sub.add_parser("import", help="Import legacy earl-biggers concepts/designs")
    sp.add_argument("--source", required=True, help="Path to legacy earl-biggers folder")
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("plan", help="Generate concepts for a brand")
    sp.add_argument("--brand", required=True)
    sp.add_argument("--lanes", nargs="*")
    sp.add_argument("--per-lane", type=int, default=5)
    sp.add_argument("--use-api", action="store_true", help="Use XAI/Grok if configured")
    sp.add_argument("--live", action="store_true")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("design", help="Build mockups for stored concepts")
    sp.add_argument("--brand", required=True)
    sp.add_argument("--concepts", nargs="*")
    sp.add_argument("--product-type", default=None, choices=["shirt", "mug", "sticker", "poster"], help="Product for visual mockup (shirt/mug/sticker/poster)")
    sp.add_argument("--live", action="store_true")
    sp.set_defaults(func=cmd_design)

    sp = sub.add_parser("list", help="Create drafts on Printify and/or Etsy")
    sp.add_argument("--brand", required=True)
    sp.add_argument("--platform", choices=["printify", "etsy", "both"], default="both")
    sp.add_argument("--concepts", nargs="*")
    sp.add_argument("--product-type", default=None, choices=["shirt", "mug", "sticker", "poster"])
    sp.add_argument("--live", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("review", help="Send Telegram review cards")
    sp.add_argument("--brand", required=True)
    sp.add_argument("--concepts", nargs="*")
    sp.add_argument("--live", action="store_true")
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser("poll", help="Drain Telegram review callbacks")
    sp.add_argument("--timeout", type=int, default=10)
    sp.add_argument("--live", action="store_true")
    sp.set_defaults(func=cmd_poll)

    sp = sub.add_parser("run", help="Run the full pipeline for a brand end-to-end")
    sp.add_argument("--brand", required=True)
    sp.add_argument("--lanes", nargs="*")
    sp.add_argument("--per-lane", type=int, default=3)
    sp.add_argument("--use-api", action="store_true")
    sp.add_argument("--product-type", default=None, choices=["shirt", "mug", "sticker", "poster"], help="Target product for mockups + listings (visual + Printify blueprint hints)")
    sp.add_argument("--skip-etsy", action="store_true")
    sp.add_argument("--skip-printify", action="store_true")
    sp.add_argument("--skip-reviews", action="store_true")
    sp.add_argument("--live", action="store_true")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("status", help="Show empire DB stats")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("mc-publish", help="Sync picks + regenerate Mission Control HTML")
    sp.add_argument("--brand")
    sp.add_argument("--limit", type=int, default=40)
    sp.set_defaults(func=cmd_mc_publish)

    sp = sub.add_parser("mc-poll", help="Apply Mission Control decisions (approve→publish, reject→close)")
    sp.add_argument("--live", action="store_true", help="Actually hit Printify; without this it's dry-run")
    sp.add_argument("--promote", action="store_true",
                    help="On approve→publish, cross-promote the mockup to social via PostBridge")
    sp.add_argument("--promote-live", action="store_true",
                    help="Publish promos for real (default: create DRAFT posts for review)")
    sp.add_argument("--promote-products", default="tee,tiedye",
                    help="Comma list of product keys eligible for promo (default tee,tiedye)")
    sp.set_defaults(func=cmd_mc_poll)

    sp = sub.add_parser("analytics", help="Show revenue/funnel/top sellers")
    sp.add_argument("--brand")
    sp.add_argument("--limit", type=int, default=10)
    sp.set_defaults(func=cmd_analytics)

    sp = sub.add_parser("gate", help="Launch the local web approval/edit gate (recommended for local use)")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=3333)
    sp.add_argument("--debug", action="store_true")
    sp.set_defaults(func=cmd_gate)

    sp = sub.add_parser("ship", help="Ship all currently approved listings for a brand (Printify publish / Etsy activate)")
    sp.add_argument("--brand", required=True)
    sp.add_argument("--live", action="store_true")
    sp.set_defaults(func=cmd_ship)

    sp = sub.add_parser("publish-site", help="Publish a brand's designs to the maddhatchery.com storefront (Nickel T's)")
    sp.add_argument("--brand", required=True)
    sp.add_argument("--category", default=None, help="Force a site category (nickel-tee|madd-tee|mug|sticker)")
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--live", action="store_true", help="Actually POST to the site (otherwise dry-run)")
    sp.set_defaults(func=cmd_publish_site)

    sp = sub.add_parser("drop", help="Process inbox image/prompt drops into the default merch bundle + push to .206")
    sp.add_argument("--brand", default="earl_biggers")
    sp.add_argument("--backend", default=None, help="Image backend override (else auto)")
    sp.add_argument("--no-publish", action="store_true", help="Skip rsync to Mission Control (.206)")
    sp.add_argument("--live", action="store_true", help="Actually create Printify drafts (else dry-run)")
    sp.set_defaults(func=cmd_drop)

    sp = sub.add_parser("watch", help="Watch the inbox folder and auto-process drops (blocking)")
    sp.add_argument("--brand", default="earl_biggers")
    sp.add_argument("--backend", default=None)
    sp.add_argument("--interval", type=int, default=10, help="Poll seconds")
    sp.add_argument("--no-publish", action="store_true")
    sp.add_argument("--live", action="store_true")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("promote", help="Cross-promote a merch mockup to social via PostBridge (draft unless --live)")
    sp.add_argument("--image", required=True, help="Path to the mockup image to post")
    sp.add_argument("--caption", default=None, help="Post caption (defaults to the image name)")
    sp.add_argument("--link", default=None, help="Optional listing URL appended to the caption")
    sp.add_argument("--platforms", default=None,
                    help="Comma list to target (e.g. instagram,tiktok,facebook); default = all image-capable")
    sp.add_argument("--live", action="store_true", help="Publish for real (else create a DRAFT post)")
    sp.add_argument("--dry-run", action="store_true", help="Print what would be posted; no API calls")
    sp.set_defaults(func=cmd_promote)

    sp = sub.add_parser("mc-open", help="Open SSH tunnel to the .206 approval UI (reachable at localhost)")
    sp.add_argument("--port", type=int, default=3333, help="Local port to forward (default 3333)")
    sp.set_defaults(func=cmd_mc_open)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
