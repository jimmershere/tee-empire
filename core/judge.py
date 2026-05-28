"""LLM-as-judge for picking the best design variant.

Uses Anthropic Claude (vision) — sends all variants in a single message and
asks the model to rank them by overall print quality + text-rendering accuracy.

Returns a list of (index, score_0_to_1, rationale) sorted best-first.

Falls back to OCR-only scoring (scoring.py) when ANTHROPIC_API_KEY isn't set.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from typing import List, Tuple

from . import scoring

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"


def judge_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def rank_variants(image_bytes_list: List[bytes],
                  expected_headline: str,
                  brand_voice: str = "") -> List[Tuple[int, float, str]]:
    """Rank variants best-first using Claude vision. Falls back to OCR."""
    if not judge_available() or not image_bytes_list:
        return _ocr_fallback(image_bytes_list, expected_headline)
    try:
        return _claude_judge(image_bytes_list, expected_headline, brand_voice)
    except Exception as e:
        # On any API failure, fall back to OCR — we want the pipeline to
        # continue producing a pick even when the judge is unavailable.
        ocr_ranked = _ocr_fallback(image_bytes_list, expected_headline)
        return [(i, s, f"OCR fallback (judge error: {type(e).__name__})") for i, s, _ in
                [(i, s, "") for i, s in [(idx, scr) for idx, scr in
                 [(o[0], o[1]) for o in ocr_ranked]]]]


def _ocr_fallback(image_bytes_list: List[bytes],
                  expected_headline: str) -> List[Tuple[int, float, str]]:
    ranked = scoring.rank_variants(image_bytes_list, expected_headline)
    return [(idx, scr, "OCR text-match") for idx, scr in ranked]


def _claude_judge(image_bytes_list: List[bytes],
                  expected_headline: str,
                  brand_voice: str) -> List[Tuple[int, float, str]]:
    model = os.getenv("EMPIRE_JUDGE_MODEL", "claude-haiku-4-5")
    api_key = os.environ["ANTHROPIC_API_KEY"]

    content: list = []
    content.append({
        "type": "text",
        "text": (
            f"You are a senior print-on-demand merchandiser. Below are "
            f"{len(image_bytes_list)} candidate t-shirt mockups generated for "
            f'the headline: "{expected_headline}".'
            + (f"\nBrand voice: {brand_voice}" if brand_voice else "")
            + "\n\nFor each variant (in order — variant 0 is the first image, "
            "variant 1 is the second, etc.), score it 0.00–1.00 on:\n"
            "  • text_accuracy — does the headline read correctly without "
            "missing/added/duplicated letters?\n"
            "  • composition — is the layout balanced, mockup-quality?\n"
            "  • illustration — is the cartoon mascot or motif on-brand?\n"
            "Then output a JSON object only (no prose, no markdown):\n"
            '{"ranking": [{"index": int, "overall": float, "rationale": '
            'string (<=25 words)}, ...]} — sorted best-first.'
        ),
    })
    for png in image_bytes_list:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(png).decode("ascii"),
            },
        })

    payload = {
        "model": model,
        "max_tokens": 600,
        "messages": [{"role": "user", "content": content}],
    }
    # Both standard API keys (sk-ant-api03-) and OAuth tokens (sk-ant-oat01-)
    # are supported. OAuth tokens use Authorization: Bearer + the oauth beta.
    is_oauth = api_key.startswith("sk-ant-oat")
    headers = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if is_oauth:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["anthropic-beta"] = "oauth-2025-04-20"
    else:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(
        ANTHROPIC_API,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Anthropic {e.code}: {e.read().decode()[:300]}") from e

    text = "".join(blk.get("text", "") for blk in body.get("content", []) if blk.get("type") == "text")
    parsed = _parse_ranking(text)
    if not parsed:
        raise RuntimeError(f"Could not parse ranking from judge: {text[:200]!r}")
    # Sort by overall descending; guarantee every input index appears.
    seen = {p[0] for p in parsed}
    for i in range(len(image_bytes_list)):
        if i not in seen:
            parsed.append((i, 0.0, "judge omitted this variant"))
    parsed.sort(key=lambda t: t[1], reverse=True)
    return parsed


def _parse_ranking(text: str) -> List[Tuple[int, float, str]]:
    """Extract {"ranking": [...]} from Claude's response."""
    text = text.strip()
    # Strip Markdown code fences if present.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first JSON object substring.
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return []
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    out: List[Tuple[int, float, str]] = []
    for item in obj.get("ranking", []):
        try:
            idx = int(item["index"])
            score = float(item["overall"])
            rationale = str(item.get("rationale", ""))[:200]
            out.append((idx, score, rationale))
        except (KeyError, ValueError, TypeError):
            continue
    return out
