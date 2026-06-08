"""PostBridge API client — cross-promote merch drops to social channels.

Reuses the publish flow proven in the ClawFirm "content-machine" dashboard
(create-upload-url -> PUT bytes -> POST /v1/posts), but fetches connected
social accounts dynamically rather than relying on hardcoded IDs (the
dashboard's were stale).

Posting to social is public, so ``create_post``/``promote_image`` default to
``is_draft=True``: a draft lands in PostBridge for review and is NOT published
until a caller explicitly passes ``is_draft=False``.
"""
from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

API_BASE = "https://api.post-bridge.com"

# Platforms that accept a single still image. YouTube is video-only, so a
# static merch mockup is never routed there.
IMAGE_PLATFORMS = {"instagram", "facebook", "twitter", "tiktok", "linkedin", "threads", "pinterest"}


class PostBridgeError(RuntimeError):
    pass


class PostBridgeClient:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("POST_BRIDGE_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
        url = f"{API_BASE}{path}"
        if dry_run:
            return {"dry_run": True, "method": method, "url": url, "payload": payload or {}}
        if not self.api_key:
            raise PostBridgeError("POST_BRIDGE_API_KEY is not configured.")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "tee-empire/1.0",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PostBridgeError(f"PostBridge API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise PostBridgeError(f"PostBridge request failed: {exc}") from exc
        return json.loads(body) if body else {}

    @staticmethod
    def _unwrap(resp: Dict[str, Any]) -> Any:
        return resp.get("data", resp)

    def list_social_accounts(self, dry_run: bool = False) -> List[Dict[str, Any]]:
        resp = self._request("GET", "/v1/social-accounts", dry_run=dry_run)
        data = self._unwrap(resp)
        return data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []

    def account_ids_for_platforms(self, platforms: Sequence[str]) -> List[int]:
        wanted = {p.lower() for p in platforms}
        return [int(a["id"]) for a in self.list_social_accounts()
                if a.get("platform", "").lower() in wanted and a.get("id") is not None]

    def upload_media(self, file_path: str, dry_run: bool = False) -> str:
        """Run PostBridge's 3-step media upload; return the media_id."""
        p = Path(file_path)
        size = p.stat().st_size if p.exists() else 0
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        if dry_run:
            return f"dryrun-media-{p.name}"
        created = self._unwrap(self._request("POST", "/v1/media/create-upload-url", payload={
            "mime_type": mime, "size_bytes": size, "name": p.name,
        }))
        media_id = created.get("media_id")
        upload_url = created.get("upload_url")
        if not media_id or not upload_url:
            raise PostBridgeError(f"create-upload-url returned no media_id/upload_url: {created}")
        body = p.read_bytes()
        put = urllib.request.Request(upload_url, data=body,
                                     headers={"Content-Type": mime}, method="PUT")
        try:
            with urllib.request.urlopen(put, timeout=120) as resp:
                if resp.status not in (200, 201, 204):
                    raise PostBridgeError(f"media PUT failed: HTTP {resp.status}")
        except urllib.error.HTTPError as exc:
            raise PostBridgeError(f"media PUT failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise PostBridgeError(f"media PUT failed: {exc}") from exc
        return str(media_id)

    def create_post(self, caption: str, *, media_ids: Optional[Sequence[str]] = None,
                    account_ids: Sequence[int], is_draft: bool = True,
                    dry_run: bool = False) -> Dict[str, Any]:
        if not account_ids:
            raise PostBridgeError("create_post requires at least one social account id.")
        payload: Dict[str, Any] = {
            "caption": caption,
            "social_accounts": [int(a) for a in account_ids],
            "is_draft": bool(is_draft),
        }
        if media_ids:
            payload["media"] = list(media_ids)
        resp = self._request("POST", "/v1/posts", payload=payload, dry_run=dry_run)
        if dry_run:
            return resp
        data = self._unwrap(resp)
        post_id = data.get("id") if isinstance(data, dict) else None
        if not post_id:
            raise PostBridgeError(f"PostBridge did not return a post id: {resp}")
        return {"post_id": post_id, "is_draft": bool(is_draft),
                "account_ids": list(account_ids), "response": data}

    def promote_image(self, image_path: str, caption: str, *,
                      platforms: Optional[Sequence[str]] = None,
                      is_draft: bool = True, dry_run: bool = False) -> Dict[str, Any]:
        """Upload ``image_path`` and create a (draft by default) post promoting it.

        ``platforms`` defaults to every connected image-capable account. Pass
        ``is_draft=False`` to publish for real.
        """
        if dry_run:
            return {"dry_run": True, "image": image_path, "caption": caption,
                    "platforms": list(platforms) if platforms else "auto",
                    "is_draft": is_draft}
        accounts = self.list_social_accounts()
        wanted = {p.lower() for p in platforms} if platforms else IMAGE_PLATFORMS
        account_ids = [int(a["id"]) for a in accounts
                       if a.get("platform", "").lower() in wanted and a.get("id") is not None]
        if not account_ids:
            raise PostBridgeError(
                f"No connected social accounts match {sorted(wanted)}; "
                f"available: {[a.get('platform') for a in accounts]}")
        media_id = self.upload_media(image_path)
        result = self.create_post(caption, media_ids=[media_id], account_ids=account_ids,
                                  is_draft=is_draft)
        result["media_id"] = media_id
        result["platforms"] = [a.get("platform") for a in accounts
                               if int(a.get("id", -1)) in set(account_ids)]
        return result
