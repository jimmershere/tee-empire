"""Printify API client (refactored from earl-biggers, multi-brand aware)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

API_BASE = "https://api.printify.com/v1"

STANDARD_UNISEX_TEE_BLUEPRINTS = {
    6: "Gildan 5000 - Unisex Heavy Cotton Tee",
    12: "Bella+Canvas 3001 - Unisex Jersey Short Sleeve Tee",
}


class PrintifyError(RuntimeError):
    pass


class PrintifyClient:
    def __init__(self, api_key: Optional[str] = None, shop_id: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("PRINTIFY_API_KEY")
        self.shop_id = shop_id or os.getenv("PRINTIFY_SHOP_ID")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.shop_id)

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
        url = f"{API_BASE}{path}"
        if dry_run:
            return {"dry_run": True, "method": method, "url": url, "payload": payload or {}}
        if not self.api_key:
            raise PrintifyError("PRINTIFY_API_KEY is not configured.")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "tee-empire/1.0",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PrintifyError(f"Printify API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise PrintifyError(f"Printify request failed: {exc}") from exc
        return json.loads(body) if body else {}

    def list_blueprints(self, dry_run: bool = False) -> Dict[str, Any]:
        return self._request("GET", "/catalog/blueprints.json", dry_run=dry_run)

    def list_print_providers(self, blueprint_id: int, dry_run: bool = False) -> Dict[str, Any]:
        return self._request("GET", f"/catalog/blueprints/{blueprint_id}/print_providers.json",
                             dry_run=dry_run)

    def list_variants(self, blueprint_id: int, provider_id: int, dry_run: bool = False) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json",
            dry_run=dry_run,
        )

    def upload_image(self, file_name: str, image_bytes: bytes, dry_run: bool = False) -> Dict[str, Any]:
        import base64
        payload = {"file_name": file_name, "contents": base64.b64encode(image_bytes).decode("ascii")}
        return self._request("POST", "/uploads/images.json", payload=payload, dry_run=dry_run)

    def create_product(self, title: str, description: str, blueprint_id: int,
                       variant_ids: Iterable[int], image_id: Optional[str] = None,
                       image_src: Optional[str] = None,
                       print_provider_id: int = 1, tags: Optional[List[str]] = None,
                       price_cents: int = 2400,
                       dry_run: bool = False) -> Dict[str, Any]:
        if not self.shop_id and not dry_run:
            raise PrintifyError("PRINTIFY_SHOP_ID is not configured.")
        variant_ids = list(variant_ids)
        if image_id:
            image_entry: Dict[str, Any] = {"id": image_id, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}
        elif image_src:
            image_entry = {"src": image_src, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}
        else:
            raise PrintifyError("create_product requires image_id or image_src.")
        payload = {
            "title": title,
            "description": description,
            "blueprint_id": blueprint_id,
            "print_provider_id": print_provider_id,
            "variants": [{"id": vid, "price": int(price_cents), "is_enabled": True}
                         for vid in variant_ids],
            "print_areas": [{
                "variant_ids": variant_ids,
                "placeholders": [{"position": "front", "images": [image_entry]}],
            }],
            "tags": tags or [],
            "visible": False,
        }
        return self._request("POST", f"/shops/{self.shop_id}/products.json",
                             payload=payload, dry_run=dry_run)

    def publish_product(self, product_id: str, dry_run: bool = False) -> Dict[str, Any]:
        if not self.shop_id and not dry_run:
            raise PrintifyError("PRINTIFY_SHOP_ID is not configured.")
        payload = {
            "title": True, "description": True, "images": True, "variants": True,
            "tags": True, "keyFeatures": True, "shipping_template": True,
        }
        return self._request("POST",
                             f"/shops/{self.shop_id}/products/{product_id}/publish.json",
                             payload=payload, dry_run=dry_run)
