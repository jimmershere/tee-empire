"""SQLite persistence for the empire.

Single DB file at empire/data/empire.db. Brand-scoped rows; idempotent upserts
by (brand, slug) for concepts/designs and (platform, external_id) for listings.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from .models import Concept, Design, Listing, Sale

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "empire.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS concepts (
    brand TEXT NOT NULL,
    slug TEXT NOT NULL,
    lane TEXT NOT NULL,
    input_handle TEXT NOT NULL,
    product_title TEXT NOT NULL,
    tagline TEXT NOT NULL,
    design_prompt TEXT NOT NULL,
    suggested_colors TEXT NOT NULL,
    tags TEXT NOT NULL,
    safety_notes TEXT NOT NULL,
    source TEXT NOT NULL,
    extra TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (brand, slug)
);

CREATE TABLE IF NOT EXISTS designs (
    brand TEXT NOT NULL,
    concept_slug TEXT NOT NULL,
    design_text TEXT NOT NULL,
    shirt_color TEXT NOT NULL,
    text_color TEXT NOT NULL,
    font_style TEXT NOT NULL,
    design_notes TEXT NOT NULL,
    mockup_path TEXT,
    mockup_url TEXT,
    source TEXT NOT NULL,
    ocr_score REAL NOT NULL DEFAULT 0,
    variant_count INTEGER NOT NULL DEFAULT 1,
    variant_paths TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (brand, concept_slug),
    FOREIGN KEY (brand, concept_slug) REFERENCES concepts(brand, slug)
);

CREATE TABLE IF NOT EXISTS listings (
    brand TEXT NOT NULL,
    concept_slug TEXT NOT NULL,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    state TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    price_cents INTEGER,
    url TEXT,
    extra TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (platform, external_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    brand TEXT NOT NULL,
    concept_slug TEXT NOT NULL,
    decision TEXT NOT NULL,
    reviewer TEXT,
    reason TEXT,
    decided_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sales (
    brand TEXT NOT NULL,
    listing_external_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    qty INTEGER NOT NULL,
    gross_cents INTEGER NOT NULL,
    fees_cents INTEGER NOT NULL,
    net_cents INTEGER NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_concepts_brand_lane ON concepts(brand, lane);
CREATE INDEX IF NOT EXISTS idx_listings_brand_state ON listings(brand, state);
CREATE INDEX IF NOT EXISTS idx_sales_brand_time ON sales(brand, occurred_at);
"""


class Store:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        cx = sqlite3.connect(self.db_path)
        cx.row_factory = sqlite3.Row
        try:
            yield cx
            cx.commit()
        finally:
            cx.close()

    # ---------- concepts ----------
    def upsert_concept(self, c: Concept) -> None:
        with self._conn() as cx:
            cx.execute(
                """INSERT INTO concepts (brand, slug, lane, input_handle, product_title, tagline,
                       design_prompt, suggested_colors, tags, safety_notes, source, extra)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(brand, slug) DO UPDATE SET
                       lane=excluded.lane, input_handle=excluded.input_handle,
                       product_title=excluded.product_title, tagline=excluded.tagline,
                       design_prompt=excluded.design_prompt, suggested_colors=excluded.suggested_colors,
                       tags=excluded.tags, safety_notes=excluded.safety_notes,
                       source=excluded.source, extra=excluded.extra""",
                (
                    c.brand, c.slug, c.lane, c.input_handle, c.product_title, c.tagline,
                    c.design_prompt, json.dumps(c.suggested_colors), json.dumps(c.tags),
                    json.dumps(c.safety_notes), c.source, json.dumps(c.extra),
                ),
            )

    def get_concept(self, brand: str, slug: str) -> Optional[Concept]:
        with self._conn() as cx:
            row = cx.execute(
                "SELECT * FROM concepts WHERE brand=? AND slug=?", (brand, slug)
            ).fetchone()
        return _row_to_concept(row) if row else None

    def list_concepts(self, brand: Optional[str] = None, lane: Optional[str] = None) -> List[Concept]:
        sql = "SELECT * FROM concepts WHERE 1=1"
        args: List[Any] = []
        if brand:
            sql += " AND brand=?"
            args.append(brand)
        if lane:
            sql += " AND lane=?"
            args.append(lane)
        sql += " ORDER BY brand, lane, slug"
        with self._conn() as cx:
            rows = cx.execute(sql, args).fetchall()
        return [_row_to_concept(r) for r in rows]

    # ---------- designs ----------
    def upsert_design(self, d: Design) -> None:
        with self._conn() as cx:
            cx.execute(
                """INSERT INTO designs (brand, concept_slug, design_text, shirt_color, text_color,
                       font_style, design_notes, mockup_path, mockup_url, source,
                       ocr_score, variant_count, variant_paths)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(brand, concept_slug) DO UPDATE SET
                       design_text=excluded.design_text, shirt_color=excluded.shirt_color,
                       text_color=excluded.text_color, font_style=excluded.font_style,
                       design_notes=excluded.design_notes, mockup_path=excluded.mockup_path,
                       mockup_url=excluded.mockup_url, source=excluded.source,
                       ocr_score=excluded.ocr_score, variant_count=excluded.variant_count,
                       variant_paths=excluded.variant_paths""",
                (
                    d.brand, d.concept_slug, d.design_text, d.shirt_color, d.text_color,
                    d.font_style, d.design_notes, d.mockup_path, d.mockup_url, d.source,
                    d.ocr_score, d.variant_count, json.dumps(d.variant_paths),
                ),
            )

    def get_design(self, brand: str, concept_slug: str) -> Optional[Design]:
        with self._conn() as cx:
            row = cx.execute(
                "SELECT * FROM designs WHERE brand=? AND concept_slug=?", (brand, concept_slug)
            ).fetchone()
        return _row_to_design(row) if row else None

    # ---------- listings ----------
    def upsert_listing(self, l: Listing) -> None:
        with self._conn() as cx:
            cx.execute(
                """INSERT INTO listings (brand, concept_slug, platform, external_id, state,
                       title, description, price_cents, url, extra, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now'))
                   ON CONFLICT(platform, external_id) DO UPDATE SET
                       state=excluded.state, title=excluded.title, description=excluded.description,
                       price_cents=excluded.price_cents, url=excluded.url, extra=excluded.extra,
                       updated_at=datetime('now')""",
                (
                    l.brand, l.concept_slug, l.platform, l.external_id, l.state,
                    l.title, l.description, l.price_cents, l.url, json.dumps(l.extra),
                ),
            )

    def list_listings(self, brand: Optional[str] = None, state: Optional[str] = None) -> List[Listing]:
        sql = "SELECT * FROM listings WHERE 1=1"
        args: List[Any] = []
        if brand:
            sql += " AND brand=?"
            args.append(brand)
        if state:
            sql += " AND state=?"
            args.append(state)
        sql += " ORDER BY updated_at DESC"
        with self._conn() as cx:
            rows = cx.execute(sql, args).fetchall()
        return [_row_to_listing(r) for r in rows]

    # ---------- reviews ----------
    def record_review(self, brand: str, concept_slug: str, decision: str, reviewer: Optional[str] = None, reason: Optional[str] = None) -> None:
        with self._conn() as cx:
            cx.execute(
                "INSERT INTO reviews (brand, concept_slug, decision, reviewer, reason) VALUES (?,?,?,?,?)",
                (brand, concept_slug, decision, reviewer, reason),
            )

    # ---------- sales ----------
    def record_sale(self, s: Sale) -> None:
        with self._conn() as cx:
            cx.execute(
                """INSERT INTO sales (brand, listing_external_id, platform, qty, gross_cents,
                       fees_cents, net_cents, occurred_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (s.brand, s.listing_external_id, s.platform, s.qty, s.gross_cents,
                 s.fees_cents, s.net_cents, s.occurred_at),
            )

    def list_sales(self, brand: Optional[str] = None, since: Optional[str] = None) -> List[Sale]:
        sql = "SELECT * FROM sales WHERE 1=1"
        args: List[Any] = []
        if brand:
            sql += " AND brand=?"
            args.append(brand)
        if since:
            sql += " AND occurred_at >= ?"
            args.append(since)
        sql += " ORDER BY occurred_at DESC"
        with self._conn() as cx:
            rows = cx.execute(sql, args).fetchall()
        return [_row_to_sale(r) for r in rows]

    # ---------- summary ----------
    def brand_stats(self) -> List[Dict[str, Any]]:
        with self._conn() as cx:
            rows = cx.execute(
                """SELECT c.brand,
                          COUNT(DISTINCT c.slug) AS concepts,
                          COUNT(DISTINCT d.concept_slug) AS designs,
                          (SELECT COUNT(*) FROM listings WHERE brand=c.brand) AS listings,
                          (SELECT COUNT(*) FROM listings WHERE brand=c.brand AND state='live') AS live,
                          (SELECT COALESCE(SUM(net_cents),0) FROM sales WHERE brand=c.brand) AS net_cents
                   FROM concepts c
                   LEFT JOIN designs d ON d.brand=c.brand AND d.concept_slug=c.slug
                   GROUP BY c.brand
                   ORDER BY c.brand"""
            ).fetchall()
        return [dict(r) for r in rows]


def _row_to_concept(r: sqlite3.Row) -> Concept:
    return Concept(
        brand=r["brand"], lane=r["lane"], slug=r["slug"], input_handle=r["input_handle"],
        product_title=r["product_title"], tagline=r["tagline"], design_prompt=r["design_prompt"],
        suggested_colors=json.loads(r["suggested_colors"]),
        tags=json.loads(r["tags"]),
        safety_notes=json.loads(r["safety_notes"]),
        source=r["source"], extra=json.loads(r["extra"]),
    )


def _row_to_design(r: sqlite3.Row) -> Design:
    return Design(
        brand=r["brand"], concept_slug=r["concept_slug"], design_text=r["design_text"],
        shirt_color=r["shirt_color"], text_color=r["text_color"], font_style=r["font_style"],
        design_notes=r["design_notes"], mockup_path=r["mockup_path"],
        mockup_url=r["mockup_url"], source=r["source"],
        ocr_score=float(r["ocr_score"] if "ocr_score" in r.keys() else 0),
        variant_count=int(r["variant_count"] if "variant_count" in r.keys() else 1),
        variant_paths=json.loads(r["variant_paths"]) if "variant_paths" in r.keys() else [],
    )


def _row_to_listing(r: sqlite3.Row) -> Listing:
    return Listing(
        brand=r["brand"], concept_slug=r["concept_slug"], platform=r["platform"],
        external_id=r["external_id"], state=r["state"], title=r["title"],
        description=r["description"], price_cents=r["price_cents"], url=r["url"],
        extra=json.loads(r["extra"]),
    )


def _row_to_sale(r: sqlite3.Row) -> Sale:
    return Sale(
        brand=r["brand"], listing_external_id=r["listing_external_id"], platform=r["platform"],
        qty=r["qty"], gross_cents=r["gross_cents"], fees_cents=r["fees_cents"],
        net_cents=r["net_cents"], occurred_at=r["occurred_at"],
    )
