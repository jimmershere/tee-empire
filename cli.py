#!/usr/bin/env python3
"""TeeEmpire CLI — `python -m empire.cli <command> ...`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

# Allow `python /app/cc/empire/cli.py ...` as well as `-m empire.cli`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    designs = orch.design(brand, concept_slugs=args.concepts or None)
    print(json.dumps({"brand": brand.slug,
                      "designed": [{"slug": d.concept_slug, "mockup": d.mockup_path}
                                   for d in designs]}, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    brand = brands_mod.load_brand(args.brand)
    orch = Orchestrator(dry_run=not args.live)
    out = {}
    if args.platform in {"printify", "both"}:
        out["printify"] = [l.to_dict() for l in
                           orch.list_to_printify(brand, concept_slugs=args.concepts or None)]
    if args.platform in {"etsy", "both"}:
        out["etsy"] = [l.to_dict() for l in
                       orch.list_to_etsy(brand, concept_slugs=args.concepts or None)]
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

    store = Store()
    decisions = mission_control.fetch_decisions()
    applied = mission_control.fetch_applied()

    # Latest-decision-per-slug semantics.
    latest = {}
    for d in decisions:
        slug = d.get("slug")
        if not slug:
            continue
        if slug not in latest or d.get("ts", "") > latest[slug].get("ts", ""):
            latest[slug] = d

    actions: list = []
    newly_applied: list = []

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
                    actions.append({"slug": slug, "decision": "approve",
                                    "printify_result": result})
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

    print(json.dumps({"decisions_seen": len(latest),
                      "newly_applied_persisted": len(newly_applied) if args.live else 0,
                      "would_apply": len(newly_applied) if not args.live else 0,
                      "actions": actions}, indent=2))
    return 0


def cmd_analytics(args: argparse.Namespace) -> int:
    out = {
        "overview": analytics.empire_overview(),
        "funnel": analytics.funnel_by_brand(),
        "top_sellers": analytics.top_sellers(brand=args.brand or None, limit=args.limit),
    }
    print(json.dumps(out, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="empire", description="TeeEmpire multi-brand t-shirt automation")
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
    sp.add_argument("--live", action="store_true")
    sp.set_defaults(func=cmd_design)

    sp = sub.add_parser("list", help="Create drafts on Printify and/or Etsy")
    sp.add_argument("--brand", required=True)
    sp.add_argument("--platform", choices=["printify", "etsy", "both"], default="both")
    sp.add_argument("--concepts", nargs="*")
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
    sp.set_defaults(func=cmd_mc_poll)

    sp = sub.add_parser("analytics", help="Show revenue/funnel/top sellers")
    sp.add_argument("--brand")
    sp.add_argument("--limit", type=int, default=10)
    sp.set_defaults(func=cmd_analytics)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
