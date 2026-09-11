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

# Minimal multi-product blueprint map (common Printify catalog IDs; override via brand.yaml or --blueprint).
# These are starting points — users should verify in their Printify catalog for their providers.
PRODUCT_BLUEPRINTS = {
    "shirt": 12,      # Bella+Canvas 3001
    "mug": 478,       # Ceramic Mug (11oz, 15oz)
    "sticker": 400,   # Kiss-Cut Stickers
    "bottle": 887,    # Stainless Steel Water Bottle, Standard Lid
    "poster": 163,    # Poster / matte print (common starting point)
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
            with urllib.request.urlopen(req, timeout=90) as resp:
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
                        dry_run: bool = False,
                        product_type: Optional[str] = None,
                        image_transform: Optional[Dict[str, Any]] = None,
                        placements: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if not self.shop_id and not dry_run:
            raise PrintifyError("PRINTIFY_SHOP_ID is not configured.")
        variant_ids = list(variant_ids)
        # Allow product_type to select a sensible blueprint when caller didn't override blueprint_id
        eff_blueprint = blueprint_id
        if product_type and not blueprint_id:
            eff_blueprint = PRODUCT_BLUEPRINTS.get(product_type, blueprint_id or 12)
        # Default: art fills the print area, centered. ``image_transform`` lets a
        # caller shrink/reposition it per product (e.g. the 15oz mug shrinks the
        # logo into the top 80% so the bottom 20% stays clear for text).
        tf: Dict[str, Any] = {"x": 0.5, "y": 0.5, "scale": 1, "angle": 0}
        if image_transform:
            tf.update({k: image_transform[k]
                       for k in ("x", "y", "scale", "angle") if k in image_transform})
        image_entry: Dict[str, Any] = {}
        if image_id:
            image_entry = {"id": image_id, **tf}
        elif image_src:
            image_entry = {"src": image_src, **tf}
        elif not placements:
            raise PrintifyError("create_product requires image_id, image_src, or placements.")
        # For non-tee products the "front" placeholder name may differ; Printify accepts "front" for most.
        # Stickers/posters often use a single print area.
        # Multi-placement (e.g. small logo on front-left chest + big art on the back).
        # placements: [{position, image_id, x, y, scale, angle}]
        if placements:
            placeholders = [{
                "position": pl["position"],
                "images": [{"id": pl["image_id"], "x": pl.get("x", 0.5), "y": pl.get("y", 0.5),
                            "scale": pl.get("scale", 1), "angle": pl.get("angle", 0)}],
            } for pl in placements if pl.get("image_id")]
        else:
            placeholders = [{"position": "front", "images": [image_entry]}]
        payload = {
            "title": title,
            "description": description,
            "blueprint_id": eff_blueprint,
            "print_provider_id": print_provider_id,
            "variants": [{"id": vid, "price": int(price_cents), "is_enabled": True}
                         for vid in variant_ids],
            "print_areas": [{"variant_ids": variant_ids, "placeholders": placeholders}],
            "tags": tags or [],
            "visible": False,
        }
        return self._request("POST", f"/shops/{self.shop_id}/products.json",
                             payload=payload, dry_run=dry_run)

    def get_product(self, product_id: str, dry_run: bool = False) -> Dict[str, Any]:
        if not self.shop_id and not dry_run:
            raise PrintifyError("PRINTIFY_SHOP_ID is not configured.")
        return self._request("GET", f"/shops/{self.shop_id}/products/{product_id}.json",
                             dry_run=dry_run)

    def replace_print_image(self, product_id: str, image_id: str,
                            dry_run: bool = False) -> Dict[str, Any]:
        """Swap the print image on an existing draft, preserving its print_areas.

        Printify rejects a print_areas update unless every product variant is
        present in ``print_areas.*.variant_ids`` (error 8251). The product is
        auto-populated with the blueprint's *full* variant set at creation, so
        we must reuse the product's existing print_areas wholesale and only
        replace the image id in each placeholder.
        """
        if dry_run:
            return {"dry_run": True, "replace_print_image": product_id, "image_id": image_id}
        product = self.get_product(product_id)
        new_areas: List[Dict[str, Any]] = []
        for area in product.get("print_areas", []):
            placeholders = []
            for ph in area.get("placeholders", []):
                imgs = ph.get("images") or []
                if imgs:
                    new_imgs = []
                    for im in imgs:
                        new_imgs.append({"id": image_id,
                                         "x": im.get("x", 0.5), "y": im.get("y", 0.5),
                                         "scale": im.get("scale", 1), "angle": im.get("angle", 0)})
                else:
                    new_imgs = [{"id": image_id, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}]
                placeholders.append({"position": ph.get("position", "front"), "images": new_imgs})
            new_areas.append({"variant_ids": area.get("variant_ids", []),
                              "placeholders": placeholders})
        return self.update_product(product_id, {"print_areas": new_areas})

    def add_text_placement(self, product_id: str, image_id: str, position: str, *,
                           x: float = 0.5, y: float = 0.5, scale: float = 1.0,
                           angle: int = 0, stack: bool = False,
                           dry_run: bool = False) -> Dict[str, Any]:
        """Place ``image_id`` (typically rendered text) at ``position`` on the draft.

        ``position`` is a Printify placeholder name available for the blueprint
        (e.g. ``front``, ``back``, ``left_sleeve``, ``right_sleeve``, ``neck``).
        Every existing ``print_areas.*.variant_ids`` set is preserved wholesale
        so Printify doesn't reject the update (error 8251), and existing
        placeholders/images are re-mapped intact.

        ``stack=True`` keeps any images already in that position and appends the
        new one (used to add text *beneath* existing front art); ``stack=False``
        replaces the images at that position only.
        """
        if dry_run:
            return {"dry_run": True, "add_text_placement": product_id,
                    "image_id": image_id, "position": position, "stack": stack}
        entry = {"id": image_id, "x": x, "y": y, "scale": scale, "angle": angle}
        product = self.get_product(product_id)
        new_areas: List[Dict[str, Any]] = []
        for area in product.get("print_areas", []):
            placeholders = []
            found = False
            for ph in area.get("placeholders", []):
                pos = ph.get("position", "front")
                remapped = [{"id": im.get("id"), "x": im.get("x", 0.5), "y": im.get("y", 0.5),
                             "scale": im.get("scale", 1), "angle": im.get("angle", 0)}
                            for im in (ph.get("images") or [])]
                if pos == position:
                    found = True
                    remapped = (remapped + [entry]) if stack else [entry]
                placeholders.append({"position": pos, "images": remapped})
            if not found:
                placeholders.append({"position": position, "images": [entry]})
            new_areas.append({"variant_ids": area.get("variant_ids", []),
                              "placeholders": placeholders})
        return self.update_product(product_id, {"print_areas": new_areas})

    def update_product(self, product_id: str,
                       updates: Dict[str, Any],
                       dry_run: bool = False) -> Dict[str, Any]:
        """PUT /shops/{shop_id}/products/{product_id}.json with partial updates.

        ``updates`` typically contains ``title``, ``description``, ``tags``.
        Re-call ``publish_product`` afterwards to push the change to the
        connected sales channel (Etsy).
        """
        if not self.shop_id and not dry_run:
            raise PrintifyError("PRINTIFY_SHOP_ID is not configured.")
        return self._request("PUT", f"/shops/{self.shop_id}/products/{product_id}.json",
                             payload=updates, dry_run=dry_run)

    def set_enabled_variants(self, product_id: str, enable_ids: Iterable[int],
                             dry_run: bool = False) -> Dict[str, Any]:
        """Enable only ``enable_ids`` on the draft, disabling every other variant.

        Reducing a tee to a single colorway makes Printify regenerate its mockup
        set to include back / model / folded shots — multi-color listings only
        get one front per color and no back. Prices are preserved. Only the
        product's currently-enabled variants (plus any newly-requested ones) are
        sent, keeping the payload small; ``print_areas`` is untouched.
        """
        enable = set(enable_ids)
        if dry_run:
            return {"dry_run": True, "set_enabled_variants": product_id,
                    "enable": sorted(enable)}
        product = self.get_product(product_id)
        payload_variants: List[Dict[str, Any]] = []
        for v in product.get("variants", []):
            vid = v.get("id")
            if v.get("is_enabled") or vid in enable:
                payload_variants.append({"id": vid, "price": v.get("price"),
                                         "is_enabled": vid in enable})
        if not any(pv["is_enabled"] for pv in payload_variants):
            raise PrintifyError(
                f"set_enabled_variants: none of {sorted(enable)} match this "
                f"product's variants — refusing to disable all.")
        return self.update_product(product_id, {"variants": payload_variants})

    def delete_product(self, product_id: str, dry_run: bool = False) -> Dict[str, Any]:
        if not self.shop_id and not dry_run:
            raise PrintifyError("PRINTIFY_SHOP_ID is not configured.")
        return self._request("DELETE", f"/shops/{self.shop_id}/products/{product_id}.json",
                             dry_run=dry_run)

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
