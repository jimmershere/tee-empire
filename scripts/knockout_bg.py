#!/usr/bin/env python3
"""Knock the white background out of print art, preserving white *inside* the design.

Print-on-demand art must be transparent or it prints as a white rectangle on every
dark garment. The naive fix — "make all near-white pixels transparent" — destroys
these designs, which are full of intentional white: chrome lettering, white pants,
parchment banners, highlights.

So this flood-fills inward from the border instead. Only background connected to
the edge is removed; an enclosed white region is untouched no matter how bright.
This is the same reasoning as ``publish_store.floodfill_transparent``, but it runs
on numpy in the project venv rather than shelling out to a separate rembg venv,
and it feathers the boundary so the cut edge isn't aliased.

Usage:
  python3 scripts/knockout_bg.py in.png out.png [--thresh 232] [--feather 1.2]
"""
from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def knockout(img: Image.Image, thresh: int = 232, feather: float = 1.2) -> Image.Image:
    rgba = np.array(img.convert("RGBA"))
    h, w = rgba.shape[:2]
    rgb = rgba[:, :, :3].astype(np.int16)

    # "Background-ish" = bright and near-neutral. Requiring low saturation stops
    # the fill bleeding into pale-but-coloured artwork (skin, sky, denim).
    bright = rgb.min(axis=2) >= thresh
    neutral = (rgb.max(axis=2) - rgb.min(axis=2)) <= 18
    candidate = bright & neutral

    # BFS inward from every border pixel that is itself background-ish.
    bg = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            if candidate[y, x] and not bg[y, x]:
                bg[y, x] = True
                q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if candidate[y, x] and not bg[y, x]:
                bg[y, x] = True
                q.append((y, x))

    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and candidate[ny, nx] and not bg[ny, nx]:
                bg[ny, nx] = True
                q.append((ny, nx))

    alpha = np.where(bg, 0, 255).astype(np.uint8)
    # Respect any alpha the source already had.
    alpha = np.minimum(alpha, rgba[:, :, 3])

    out = Image.fromarray(np.dstack([rgba[:, :, :3], alpha]), "RGBA")
    if feather > 0:
        a = out.getchannel("A").filter(ImageFilter.GaussianBlur(feather))
        out.putalpha(a)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--thresh", type=int, default=232,
                    help="min channel value to count as background (default 232)")
    ap.add_argument("--feather", type=float, default=1.2, help="edge blur radius")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        return 2
    im = Image.open(src)
    before = im.size
    out = knockout(im, args.thresh, args.feather)

    a = np.array(out.getchannel("A"))
    pct = int((a < 16).sum() * 100 / a.size)
    corners = [int(a[0, 0]), int(a[0, -1]), int(a[-1, 0]), int(a[-1, -1])]
    Path(args.dst).parent.mkdir(parents=True, exist_ok=True)
    out.save(args.dst, "PNG", optimize=True)
    print(f"  {src.name[:44]:<44} {before[0]}x{before[1]}  "
          f"transparent={pct}%  corners={corners}  -> {args.dst}")
    if max(corners) >= 16:
        print("  WARNING: corners still opaque — background may not be uniform white",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
