"""Etsy Open API v3 client.

OAuth 2.0 flow + listing/image/inventory endpoints. Per Etsy's docs:
  - Auth base:    https://www.etsy.com/oauth/connect
  - Token base:   https://api.etsy.com/v3/public/oauth/token
  - API base:     https://openapi.etsy.com/v3
  - Listings:     POST /application/shops/{shop_id}/listings
  - Image:        POST /application/shops/{shop_id}/listings/{listing_id}/images
  - Inventory:    PUT  /application/listings/{listing_id}/inventory

Auth requires an x-api-key header on every call, plus a Bearer token from the
OAuth exchange. This client supports two modes:

1. Personal access token (PAT) — set ETSY_API_KEY (keystring) + ETSY_OAUTH_TOKEN.
2. Full OAuth flow — exchange_code() / refresh_token() helpers included.

dry_run mode returns canned response shapes so the orchestrator runs end-to-end
without any real shop / token.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

OAUTH_AUTHZ = "https://www.etsy.com/oauth/connect"
OAUTH_TOKEN = "https://api.etsy.com/v3/public/oauth/token"
API_BASE = "https://openapi.etsy.com/v3"


class EtsyError(RuntimeError):
    pass


class EtsyClient:
    def __init__(self, keystring: Optional[str] = None, oauth_token: Optional[str] = None,
                 shop_id: Optional[str] = None) -> None:
        self.keystring = keystring or os.getenv("ETSY_API_KEY")
        self.oauth_token = oauth_token or os.getenv("ETSY_OAUTH_TOKEN")
        self.shop_id = shop_id or os.getenv("ETSY_SHOP_ID")

    @property
    def configured(self) -> bool:
        return bool(self.keystring and self.oauth_token and self.shop_id)

    # ---------- HTTP ----------
    def _request(self, method: str, path: str,
                 payload: Optional[Dict[str, Any]] = None,
                 form: Optional[Dict[str, Any]] = None,
                 raw_body: Optional[bytes] = None,
                 content_type: Optional[str] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
        url = f"{API_BASE}{path}"
        if dry_run:
            return {
                "dry_run": True, "method": method, "url": url,
                "payload": payload or form or {},
                "synthetic_id": _synthetic_id(path),
            }
        if not self.keystring or not self.oauth_token:
            raise EtsyError("ETSY_API_KEY and ETSY_OAUTH_TOKEN must be configured.")
        headers = {
            "x-api-key": self.keystring,
            "Authorization": f"Bearer {self.oauth_token}",
            "User-Agent": "tee-empire/1.0",
        }
        body: Optional[bytes] = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif form is not None:
            body = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif raw_body is not None:
            body = raw_body
            if content_type:
                headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                rb = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EtsyError(f"Etsy API error {exc.code} on {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise EtsyError(f"Etsy request failed: {exc}") from exc
        return json.loads(rb) if rb else {}

    # ---------- OAuth helpers ----------
    @staticmethod
    def build_authorize_url(client_id: str, redirect_uri: str,
                            scopes: Optional[List[str]] = None,
                            state: Optional[str] = None,
                            code_verifier: Optional[str] = None) -> Dict[str, str]:
        scopes = scopes or ["listings_w", "listings_r", "shops_r", "transactions_r"]
        verifier = code_verifier or _b64url(secrets.token_bytes(32))
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        st = state or secrets.token_urlsafe(16)
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": st,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return {
            "url": f"{OAUTH_AUTHZ}?{urllib.parse.urlencode(params)}",
            "state": st,
            "code_verifier": verifier,
        }

    @staticmethod
    def exchange_code(client_id: str, redirect_uri: str, code: str,
                      code_verifier: str) -> Dict[str, Any]:
        body = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
        }).encode("utf-8")
        req = urllib.request.Request(OAUTH_TOKEN, data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def refresh(client_id: str, refresh_token: str) -> Dict[str, Any]:
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        }).encode("utf-8")
        req = urllib.request.Request(OAUTH_TOKEN, data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ---------- Listings ----------
    def create_draft_listing(self, *, title: str, description: str, price_usd: float,
                             quantity: int = 999, tags: Optional[List[str]] = None,
                             shipping_profile_id: Optional[int] = None,
                             taxonomy_id: int = 1316,  # Clothing > Adult Clothing > Tops > T-shirts
                             who_made: str = "i_did", when_made: str = "made_to_order",
                             is_supply: bool = False, materials: Optional[List[str]] = None,
                             dry_run: bool = False) -> Dict[str, Any]:
        if not self.shop_id and not dry_run:
            raise EtsyError("ETSY_SHOP_ID not configured.")
        form: Dict[str, Any] = {
            "quantity": quantity,
            "title": title[:140],
            "description": description,
            "price": f"{price_usd:.2f}",
            "who_made": who_made,
            "when_made": when_made,
            "taxonomy_id": taxonomy_id,
            "is_supply": "false" if not is_supply else "true",
            "state": "draft",
            "should_auto_renew": "true",
        }
        if shipping_profile_id:
            form["shipping_profile_id"] = shipping_profile_id
        if tags:
            form["tags"] = ",".join(tags[:13])
        if materials:
            form["materials"] = ",".join(materials[:13])
        return self._request("POST", f"/application/shops/{self.shop_id}/listings",
                             form=form, dry_run=dry_run)

    def upload_listing_image(self, listing_id: int, image_bytes: bytes,
                             rank: int = 1, dry_run: bool = False) -> Dict[str, Any]:
        if dry_run:
            return {"dry_run": True, "listing_id": listing_id, "rank": rank,
                    "synthetic_image_id": _synthetic_id(f"image-{listing_id}-{rank}")}
        # Real upload is multipart/form-data. Build manually to avoid extra deps.
        boundary = "----empire" + secrets.token_hex(12)
        body = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"image\"; filename=\"design.png\"\r\n"
            f"Content-Type: image/png\r\n\r\n"
        ).encode("utf-8") + image_bytes + (
            f"\r\n--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"rank\"\r\n\r\n{rank}\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        return self._request(
            "POST",
            f"/application/shops/{self.shop_id}/listings/{listing_id}/images",
            raw_body=body, content_type=f"multipart/form-data; boundary={boundary}",
        )

    def update_listing_state(self, listing_id: int, state: str = "active",
                             dry_run: bool = False) -> Dict[str, Any]:
        if state not in {"active", "draft", "inactive"}:
            raise EtsyError(f"Invalid state: {state}")
        return self._request("PATCH",
                             f"/application/shops/{self.shop_id}/listings/{listing_id}",
                             form={"state": state}, dry_run=dry_run)

    def get_shop_receipts(self, *, min_created: Optional[int] = None,
                          limit: int = 25, offset: int = 0,
                          dry_run: bool = False) -> Dict[str, Any]:
        qs: Dict[str, Any] = {"limit": limit, "offset": offset}
        if min_created:
            qs["min_created"] = min_created
        path = f"/application/shops/{self.shop_id}/receipts?{urllib.parse.urlencode(qs)}"
        return self._request("GET", path, dry_run=dry_run)


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _synthetic_id(seed: str) -> str:
    return "dryrun-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
