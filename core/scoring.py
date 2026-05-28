"""OCR-based quality scoring for design variants.

Uses Tesseract via subprocess (no pytesseract dependency). Scores each variant
by string similarity between OCR-extracted text and the expected headline.
Higher = closer match. Range [0.0, 1.0].
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from difflib import SequenceMatcher
from io import BytesIO
from typing import Iterable, List, Optional, Tuple

try:
    from PIL import Image, ImageOps
    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PIL_AVAILABLE = False


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_text(image_bytes: bytes, psms: Iterable[int] = (6, 11)) -> List[str]:
    """Run Tesseract on the image (after inverting for white-on-dark designs).
    Returns one OCR string per PSM mode. Empty list if tesseract isn't available.
    """
    if not tesseract_available() or not _PIL_AVAILABLE:
        return []
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    # Most tee designs are white text on dark background — Tesseract is tuned
    # for the opposite, so invert.
    inverted = ImageOps.invert(img)
    results: List[str] = []
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        inverted.save(tmp.name)
        for psm in psms:
            try:
                r = subprocess.run(
                    ["tesseract", tmp.name, "stdout", "--psm", str(psm)],
                    capture_output=True, text=True, timeout=15,
                )
                results.append(r.stdout.strip())
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
    import os
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
    return results


def _normalize(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", s.upper())


def score_text_match(image_bytes: bytes, expected_headline: str) -> float:
    """Score how well the OCR-extracted text matches the expected headline.

    Returns max(SequenceMatcher.ratio) across all PSM attempts. 0.0 if no OCR.
    Strips non-alphanumerics and uppercases both sides before comparison.
    """
    expected_norm = _normalize(expected_headline)
    if not expected_norm:
        return 0.0
    candidates = ocr_text(image_bytes)
    if not candidates:
        return 0.0
    best = 0.0
    for raw in candidates:
        candidate_norm = _normalize(raw)
        if not candidate_norm:
            continue
        # Try both directions: full string match and "expected is substring of OCR".
        full = SequenceMatcher(None, candidate_norm, expected_norm).ratio()
        # Also reward partial substring containment (OCR might pick up extra noise).
        substring = 0.0
        for window_start in range(max(0, len(candidate_norm) - len(expected_norm) + 1)):
            window = candidate_norm[window_start:window_start + len(expected_norm)]
            substring = max(substring, SequenceMatcher(None, window, expected_norm).ratio())
        best = max(best, full, substring)
    return round(best, 3)


def rank_variants(image_bytes_list: List[bytes],
                  expected_headline: str) -> List[Tuple[int, float]]:
    """Return [(original_index, score), ...] sorted best-first."""
    scored = [(i, score_text_match(b, expected_headline)) for i, b in enumerate(image_bytes_list)]
    return sorted(scored, key=lambda t: t[1], reverse=True)
