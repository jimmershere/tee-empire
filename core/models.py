"""Dataclass models shared across the empire."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Brand:
    slug: str
    name: str
    voice: str
    niches: List[str] = field(default_factory=list)
    palette: List[str] = field(default_factory=list)
    lanes: List[str] = field(default_factory=list)
    printify_shop_id: Optional[str] = None
    printify_blueprint_id: int = 12
    printify_print_provider_id: int = 6
    printify_variant_ids: List[int] = field(default_factory=list)
    printify_price_cents: int = 2400
    etsy_shop_id: Optional[str] = None
    adult_listing_default: bool = False
    pricing: Dict[str, Any] = field(default_factory=dict)
    review_chat_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Concept:
    brand: str
    lane: str
    slug: str
    input_handle: str
    product_title: str
    tagline: str
    design_prompt: str
    suggested_colors: List[str]
    tags: List[str]
    safety_notes: List[str]
    source: str = "template"
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Design:
    concept_slug: str
    brand: str
    design_text: str
    shirt_color: str
    text_color: str
    font_style: str
    design_notes: str = ""
    mockup_path: Optional[str] = None
    mockup_url: Optional[str] = None
    source: str = "compositor"
    ocr_score: float = 0.0           # 0..1 — match between OCR text and headline
    variant_count: int = 1            # how many candidates were generated
    variant_paths: List[str] = field(default_factory=list)  # paths of all candidates

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Listing:
    brand: str
    concept_slug: str
    platform: str  # "printify" | "etsy"
    external_id: str
    state: str  # "draft" | "pending_review" | "approved" | "live" | "rejected"
    title: str
    description: str = ""
    price_cents: Optional[int] = None
    url: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Sale:
    brand: str
    listing_external_id: str
    platform: str
    qty: int
    gross_cents: int
    fees_cents: int
    net_cents: int
    occurred_at: str  # ISO-8601

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
