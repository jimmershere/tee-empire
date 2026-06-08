"""End-to-end pipeline runner for a brand.

Pipeline steps (each is independently runnable):
  1. plan   — pick lane(s) + handles → Concepts (store)
  2. design — build Design + render mockup PNG (store + filesystem)
  3. list   — push to Printify + Etsy as drafts (store as Listing rows)
  4. review — send Telegram review card (per brand chat)
  5. ship   — on approval, publish/activate listings

Each step is idempotent — re-running just refreshes state.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import brands as brands_mod
from . import concepts as concepts_mod
from . import designs as designs_mod
from . import etsy as etsy_mod
from . import hitl as hitl_mod
from . import printify as printify_mod
from . import util
from .models import Brand, Concept, Design, Listing
from .store import Store


@dataclass
class RunReport:
    brand: str
    planned: List[str]
    designed: List[str]
    listed_printify: List[str]
    listed_etsy: List[str]
    reviews_sent: List[str]
    errors: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "brand": self.brand,
            "planned": self.planned,
            "designed": self.designed,
            "listed_printify": self.listed_printify,
            "listed_etsy": self.listed_etsy,
            "reviews_sent": self.reviews_sent,
            "errors": self.errors,
        }


class Orchestrator:
    def __init__(self, store: Optional[Store] = None, dry_run: bool = True) -> None:
        self.store = store or Store()
        self.dry_run = dry_run

    # -------- step 1: plan --------
    def plan(self, brand: Brand, *, lanes: Optional[List[str]] = None,
             per_lane: int = 5, use_api: bool = False) -> List[Concept]:
        lanes = lanes or brand.lanes
        out: List[Concept] = []
        for lane in lanes:
            seeds = brands_mod.lane_seeds(brand.slug, lane)
            if not seeds:
                continue
            for handle in seeds[:per_lane]:
                concept = concepts_mod.generate_concept(brand, handle, lane, use_api=use_api)
                self.store.upsert_concept(concept)
                out.append(concept)
        return out

    # -------- step 2: design --------
    def design(self, brand: Brand, concept_slugs: Optional[List[str]] = None,
               product_type: Optional[str] = None) -> List[Design]:
        if concept_slugs is None:
            concepts = self.store.list_concepts(brand=brand.slug)
        else:
            concepts = [c for c in (self.store.get_concept(brand.slug, s) for s in concept_slugs) if c]
        out: List[Design] = []
        for c in concepts:
            existing = self.store.get_design(brand.slug, c.slug)
            d = existing or designs_mod.design_from_concept(brand, c)
            # Pass product_type through for multi-product mockups (shirt/mug/sticker/poster)
            d = designs_mod.build_mockup(brand, c, d, dry_run=self.dry_run, product_type=product_type)
            # Persist product_type hint for later listing/shipping
            if product_type:
                d.extra = getattr(d, "extra", {}) or {}
                d.extra["product_type"] = product_type
            self.store.upsert_design(d)
            out.append(d)
        return out

    # -------- step 3: list --------
    def list_to_printify(self, brand: Brand, concept_slugs: Optional[List[str]] = None,
                          blueprint_id: Optional[int] = None,
                          variant_ids: Optional[List[int]] = None,
                          print_provider_id: Optional[int] = None,
                          product_type: Optional[str] = None) -> List[Listing]:
        client = printify_mod.PrintifyClient(shop_id=brand.printify_shop_id)
        # Support multi-product via explicit product_type or stored on design/listing
        pt = product_type
        blueprint_id = blueprint_id or brand.printify_blueprint_id
        print_provider_id = print_provider_id or brand.printify_print_provider_id
        variant_ids = variant_ids or brand.printify_variant_ids or [1]
        price_cents = brand.printify_price_cents
        concepts = self._select_concepts(brand, concept_slugs)
        results: List[Listing] = []
        for c in concepts:
            design = self.store.get_design(brand.slug, c.slug)
            if not design or not design.mockup_path:
                continue
            # Resolve per-concept product_type (from design extra or listing hint)
            if not pt:
                pt = (getattr(design, "extra", None) or {}).get("product_type") if hasattr(design, "extra") else None
            try:
                image_bytes = Path(design.mockup_path).read_bytes()
                upload = client.upload_image(f"{c.slug}.png", image_bytes, dry_run=self.dry_run)
                image_id = upload.get("id") or upload.get("synthetic_id") or "dryrun-image"
                listing_title = util.sanitize_for_marketplace(c.product_title)
                listing_tags = [util.sanitize_for_marketplace(t) for t in c.tags]
                description = util.sanitize_for_marketplace(
                    f"{c.product_title} — {c.tagline}\n\n"
                    f"Design brief: {c.design_prompt}\n\n"
                    f"Colors: {', '.join(c.suggested_colors)}"
                )
                # Let PrintifyClient pick blueprint by product_type when not explicitly passed
                created = client.create_product(
                    title=listing_title, description=description,
                    blueprint_id=blueprint_id, variant_ids=variant_ids,
                    image_id=image_id, print_provider_id=print_provider_id,
                    tags=listing_tags, price_cents=price_cents, dry_run=self.dry_run,
                    product_type=pt,
                )
                external_id = str(created.get("id") or f"dryrun-{c.slug}")
                extra = {"blueprint_id": blueprint_id, "variant_ids": variant_ids,
                         "print_provider_id": print_provider_id, "upload": upload,
                         "create_response": created}
                if pt:
                    extra["product_type"] = pt
                listing = Listing(
                    brand=brand.slug, concept_slug=c.slug, platform="printify",
                    external_id=external_id, state="pending_review",
                    title=listing_title, description=description,
                    extra=extra,
                )
                self.store.upsert_listing(listing)
                results.append(listing)
            except Exception as exc:
                err_listing = Listing(
                    brand=brand.slug, concept_slug=c.slug, platform="printify",
                    external_id=f"error-{c.slug}-{int(time.time())}",
                    state="error",
                    title=c.product_title,
                    description=f"{type(exc).__name__}: {exc}",
                    extra={"error": str(exc), "error_type": type(exc).__name__},
                )
                try:
                    self.store.upsert_listing(err_listing)
                except Exception:
                    pass
                results.append(err_listing)
        return results

    def list_to_etsy(self, brand: Brand, concept_slugs: Optional[List[str]] = None,
                      price_usd: float = 24.0,
                      product_type: Optional[str] = None) -> List[Listing]:
        client = etsy_mod.EtsyClient(shop_id=brand.etsy_shop_id)
        concepts = self._select_concepts(brand, concept_slugs)
        results: List[Listing] = []
        for c in concepts:
            design = self.store.get_design(brand.slug, c.slug)
            if not design or not design.mockup_path:
                continue
            pt = product_type or ((getattr(design, "extra", None) or {}).get("product_type") if hasattr(design, "extra") else None) or "shirt"
            try:
                listing_title = util.sanitize_for_marketplace(c.product_title)
                listing_tags = [util.sanitize_for_marketplace(t) for t in c.tags]
                # Generic POD description; Printify channel will often be the real source of truth for variants/images
                prod_desc = {
                    "shirt": "Made-to-order soft tee. Bella+Canvas 3001 unisex jersey. Ships fast.",
                    "mug": "15oz ceramic mug. Dishwasher & microwave safe. Made-to-order.",
                    "sticker": "High-quality vinyl sticker. Weather resistant. Made-to-order.",
                    "poster": "Museum-quality poster print on thick matte paper. Made-to-order.",
                }.get(pt, "Made-to-order POD item. Ships fast.")
                description = util.sanitize_for_marketplace(
                    f"{c.tagline}\n\n{c.product_title}\n\n{prod_desc}\n\nColors/Material: {', '.join(c.suggested_colors)}"
                )
                created = client.create_draft_listing(
                    title=listing_title, description=description, price_usd=price_usd,
                    quantity=999, tags=listing_tags, dry_run=self.dry_run,
                )
                if self.dry_run:
                    listing_id = f"dryrun-{c.slug}"
                else:
                    listing_id = str(created.get("listing_id") or f"dryrun-{c.slug}")
                img_bytes = Path(design.mockup_path).read_bytes()
                if not self.dry_run:
                    client.upload_listing_image(int(listing_id), img_bytes, rank=1,
                                                dry_run=self.dry_run)
                extra = {"create_response": created, "product_type": pt}
                listing = Listing(
                    brand=brand.slug, concept_slug=c.slug, platform="etsy",
                    external_id=listing_id, state="pending_review",
                    title=listing_title, description=description,
                    price_cents=int(round(price_usd * 100)),
                    extra=extra,
                )
                self.store.upsert_listing(listing)
                results.append(listing)
            except Exception as exc:
                err_listing = Listing(
                    brand=brand.slug, concept_slug=c.slug, platform="etsy",
                    external_id=f"error-{c.slug}-{int(time.time())}", state="error",
                    title=c.product_title,
                    description=f"{type(exc).__name__}: {exc}",
                    extra={"error": str(exc), "error_type": type(exc).__name__},
                )
                try:
                    self.store.upsert_listing(err_listing)
                except Exception:
                    pass
                results.append(err_listing)
        return results

    # -------- step 4: review --------
    def send_reviews(self, brand: Brand,
                     concept_slugs: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        bot = hitl_mod.HITLBot(dry_run=self.dry_run, store=self.store)
        concepts = self._select_concepts(brand, concept_slugs)
        out: List[Dict[str, Any]] = []
        for c in concepts:
            design = self.store.get_design(brand.slug, c.slug)
            mockup = design.mockup_path if design else None
            result = bot.send_review(brand, c.slug, mockup_path=mockup)
            out.append({"slug": c.slug, "result": result})
        return out

    # -------- helpers --------
    def _select_concepts(self, brand: Brand,
                         concept_slugs: Optional[List[str]] = None) -> List[Concept]:
        if concept_slugs:
            return [c for c in (self.store.get_concept(brand.slug, s) for s in concept_slugs) if c]
        return self.store.list_concepts(brand=brand.slug)

    # -------- full run --------
    def full_run(self, brand: Brand, *, lanes: Optional[List[str]] = None,
                  per_lane: int = 5, use_api: bool = False,
                  send_etsy: bool = True, send_printify: bool = True,
                  send_reviews: bool = True,
                  product_type: Optional[str] = None) -> RunReport:
        errors: List[Dict[str, Any]] = []
        planned = self.plan(brand, lanes=lanes, per_lane=per_lane, use_api=use_api)
        designed = self.design(brand, [c.slug for c in planned], product_type=product_type)
        listed_printify: List[Listing] = []
        listed_etsy: List[Listing] = []
        if send_printify:
            listed_printify = self.list_to_printify(brand, [c.slug for c in planned], product_type=product_type)
        if send_etsy:
            listed_etsy = self.list_to_etsy(brand, [c.slug for c in planned], product_type=product_type)
        reviews: List[Dict[str, Any]] = []
        if send_reviews:
            reviews = self.send_reviews(brand, [c.slug for c in planned])
        return RunReport(
            brand=brand.slug,
            planned=[c.slug for c in planned],
            designed=[d.concept_slug for d in designed],
            listed_printify=[l.external_id for l in listed_printify if l.state != "error"],
            listed_etsy=[l.external_id for l in listed_etsy if l.state != "error"],
            reviews_sent=[r["slug"] for r in reviews],
            errors=errors,
        )
