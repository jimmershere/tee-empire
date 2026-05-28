"""Multi-brand Telegram HITL review bot.

Refactored from earl-biggers/hitl_review_bot.py. Brand-aware routing:
  - Each brand can have its own review_chat_id (in brand.yaml).
  - Callbacks carry brand + concept_slug; approvals trigger Etsy/Printify publish.
  - State lives in empire/data/hitl_state.json (offset + pending replies).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from . import printify
from . import etsy
from .models import Brand
from .store import Store

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
STATE_PATH = DATA_DIR / "hitl_state.json"


class TelegramError(RuntimeError):
    pass


class HITLBot:
    def __init__(self, token: Optional[str] = None, dry_run: bool = False,
                 store: Optional[Store] = None) -> None:
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN") or _read_token_file()
        self.dry_run = dry_run
        self.store = store or Store()
        self.api_base = f"https://api.telegram.org/bot{self.token}" if self.token else None
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not STATE_PATH.exists():
            STATE_PATH.write_text(json.dumps({"offset": 0, "pending_reason": {}, "context": {}}))

    # ---------- state ----------
    def _load(self) -> Dict[str, Any]:
        return json.loads(STATE_PATH.read_text())

    def _save(self, state: Dict[str, Any]) -> None:
        STATE_PATH.write_text(json.dumps(state, indent=2))

    # ---------- HTTP ----------
    def _post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.dry_run or not self.api_base:
            return {"ok": True, "dry_run": True, "method": method, "payload": payload}
        req = urllib.request.Request(
            f"{self.api_base}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TelegramError(f"Telegram {method} {exc.code}: {detail}") from exc
        parsed = json.loads(body)
        if not parsed.get("ok"):
            raise TelegramError(f"Telegram {method} returned error: {parsed}")
        return parsed

    # ---------- review send ----------
    def send_review(self, brand: Brand, concept_slug: str, *,
                    mockup_path: Optional[str] = None,
                    extra_caption: str = "") -> Dict[str, Any]:
        concept = self.store.get_concept(brand.slug, concept_slug)
        if not concept:
            raise ValueError(f"Concept not found: {brand.slug}/{concept_slug}")
        chat_id = brand.review_chat_id or os.getenv("DEFAULT_REVIEW_CHAT_ID", "")
        if not chat_id and not self.dry_run:
            raise TelegramError(f"No review_chat_id for brand {brand.slug}")
        design = self.store.get_design(brand.slug, concept_slug)
        quality_line = ""
        if design and design.variant_count > 1:
            score_pct = int(round(design.ocr_score * 100))
            warn = "  ⚠ low score, consider regen" if design.ocr_score < 0.6 else ""
            quality_line = (
                f"\nQuality: OCR text-match {score_pct}% "
                f"(best of {design.variant_count} variants){warn}"
            )
        caption = (
            f"[{brand.name}] {concept.product_title}\n"
            f"Lane: {concept.lane}\n"
            f"Tagline: {concept.tagline}\n"
            f"Colors: {', '.join(concept.suggested_colors)}\n"
            f"Slug: {concept.slug}"
            f"{quality_line}"
        )
        if extra_caption:
            caption += "\n" + extra_caption
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ APPROVE", "callback_data": f"a|{brand.slug}|{concept.slug}"[:64]},
                {"text": "❌ REJECT", "callback_data": f"r|{brand.slug}|{concept.slug}"[:64]},
                {"text": "✏️ EDIT", "callback_data": f"e|{brand.slug}|{concept.slug}"[:64]},
            ]]
        }
        state = self._load()
        state.setdefault("context", {})[concept.slug] = {"brand": brand.slug}
        self._save(state)

        if mockup_path and Path(mockup_path).exists() and not self.dry_run and self.api_base:
            return self._post_multipart_photo(chat_id, mockup_path, caption, keyboard)
        method = "sendMessage"
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": caption, "reply_markup": keyboard}
        return self._post(method, payload)

    def _post_multipart_photo(self, chat_id: str, photo_path: str, caption: str,
                              reply_markup: Dict[str, Any]) -> Dict[str, Any]:
        import secrets
        boundary = "----empire" + secrets.token_hex(12)
        with open(photo_path, "rb") as f:
            photo_bytes = f.read()
        parts = []
        for name, value in (("chat_id", chat_id), ("caption", caption),
                            ("reply_markup", json.dumps(reply_markup))):
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        parts.append((
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"photo\"; filename=\"mockup.png\"\r\n"
            f"Content-Type: image/png\r\n\r\n"
        ).encode("utf-8"))
        parts.append(photo_bytes)
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)
        req = urllib.request.Request(
            f"{self.api_base}/sendPhoto",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ---------- polling ----------
    def poll_once(self, on_approve: Optional[Callable[[Brand, str], Dict[str, Any]]] = None,
                  timeout: int = 20) -> int:
        if self.dry_run or not self.api_base:
            return 0
        state = self._load()
        params = urllib.parse.urlencode({"timeout": timeout, "offset": state.get("offset", 0)})
        url = f"{self.api_base}/getUpdates?{params}"
        with urllib.request.urlopen(url, timeout=timeout + 5) as resp:
            updates = json.loads(resp.read().decode("utf-8"))
        count = 0
        from .brands import load_brand
        for update in updates.get("result", []):
            count += 1
            state["offset"] = update["update_id"] + 1
            cb = update.get("callback_query")
            if cb:
                action, brand_slug, concept_slug = (cb.get("data", "") + "||").split("|", 2)
                if action in {"a", "r", "e"} and brand_slug:
                    try:
                        brand = load_brand(brand_slug)
                    except FileNotFoundError:
                        self._answer(cb["id"], f"Unknown brand {brand_slug}")
                        continue
                    if action == "a":
                        self.store.record_review(brand_slug, concept_slug, "approved")
                        result = on_approve(brand, concept_slug) if on_approve else {"approved": True}
                        self._answer(cb["id"], "Approved.")
                        listing = self.store.list_listings(brand=brand_slug)
                        for l in listing:
                            if l.concept_slug == concept_slug:
                                l.state = "approved"
                                self.store.upsert_listing(l)
                                break
                    elif action == "r":
                        self.store.record_review(brand_slug, concept_slug, "rejected")
                        state.setdefault("pending_reason", {})[str(cb["from"]["id"])] = f"{brand_slug}|{concept_slug}"
                        self._answer(cb["id"], "Rejected. Send reason next.")
                    elif action == "e":
                        self.store.record_review(brand_slug, concept_slug, "needs_edit")
                        self._answer(cb["id"], "Marked needs edit.")
        self._save(state)
        return count

    def _answer(self, callback_id: str, text: str) -> None:
        self._post("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def default_approve_handler(brand: Brand, concept_slug: str, *, store: Optional[Store] = None,
                            dry_run: bool = True) -> Dict[str, Any]:
    """Default approve action: publish to whatever platform listings exist for this concept."""
    store = store or Store()
    results: Dict[str, Any] = {}
    for listing in store.list_listings(brand=brand.slug):
        if listing.concept_slug != concept_slug:
            continue
        if listing.platform == "printify":
            client = printify.PrintifyClient(shop_id=brand.printify_shop_id)
            results["printify"] = client.publish_product(listing.external_id, dry_run=dry_run)
        elif listing.platform == "etsy":
            client = etsy.EtsyClient(shop_id=brand.etsy_shop_id)
            results["etsy"] = client.update_listing_state(int(listing.external_id), "active",
                                                         dry_run=dry_run)
    return results


def _read_token_file() -> Optional[str]:
    for path in (
        Path.home() / ".openclaw" / "secrets" / "telegram-bot-token.txt",
        Path(__file__).resolve().parents[1] / ".telegram_token",
    ):
        if path.exists():
            return path.read_text().strip()
    return None
