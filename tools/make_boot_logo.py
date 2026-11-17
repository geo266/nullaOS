#!/usr/bin/env python3
"""
make_boot_logo.py — build assets/ui/boot_logo.png for the CRT

Matches the rest of the UI asset pipeline (tools/build_ui_assets.py):

    source art  ->  scale to HALF the final size
                ->  ordered dither, Bayer 4x4, 6 levels per channel
                ->  upscale 2x with NEAREST

So every dither cell ends up 2x2 pixels. That matters on the Aiwa: 1 px detail
flickers in 480i, 2x2 does not. The logo is drawn 1:1 by the boot screen, so
the pattern stays crisp — never scale a dithered asset at runtime.

Alpha is dithered too (4 levels), otherwise the art's soft drop shadow would
turn into a hard jagged edge.

Needs only numpy + PySide6 (both already required by the app) — no Pillow.

Usage:
    python tools/make_boot_logo.py                     # 288 px tall (safe-area max)
    python tools/make_boot_logo.py --height 320
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DEFAULT = PROJECT_ROOT / "reference" / "sources" / "artboard_logo.png"
OUT_DEFAULT = PROJECT_ROOT / "assets" / "ui" / "boot_logo.png"

BAYER = np.array([[0, 8, 2, 10],
                  [12, 4, 14, 6],
                  [3, 11, 1, 9],
                  [15, 7, 13, 5]]) / 16.0


# ── image I/O (Qt, so no Pillow dependency) ──────────────────────────────────

def load_rgba(path: Path) -> np.ndarray:
    img = QImage(str(path)).convertToFormat(QImage.Format_RGBA8888)
    if img.isNull():
        raise SystemExit(f"cannot read image: {path}")
    h, w = img.height(), img.width()
    buf = img.constBits()
    return np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4).copy()


def save_rgba(arr: np.ndarray, path: Path) -> None:
    h, w = arr.shape[:2]
    arr = np.ascontiguousarray(arr)
    img = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not img.save(str(path), "PNG"):
        raise SystemExit(f"cannot write {path}")


def resize_rgba(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    arr = np.ascontiguousarray(arr)
    sh, sw = arr.shape[:2]
    img = QImage(arr.data, sw, sh, sw * 4, QImage.Format_RGBA8888).copy()
    sm = img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    sm = sm.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(sm.constBits(), dtype=np.uint8).reshape(h, w, 4).copy()


def trim(arr: np.ndarray, pad: int = 6) -> np.ndarray:
    """Crop to the visible (alpha > 0) content, plus a small margin."""
    a = arr[..., 3]
    ys, xs = np.where(a > 8)
    if not len(ys):
        return arr
    y0, y1 = max(0, ys.min() - pad), min(arr.shape[0], ys.max() + 1 + pad)
    x0, x1 = max(0, xs.min() - pad), min(arr.shape[1], xs.max() + 1 + pad)
    return arr[y0:y1, x0:x1]


# ── the pipeline ────────────────────────────────────────────────────────────

def dither_rgba(src: np.ndarray, out_w: int, out_h: int,
                levels: int = 6, alpha_levels: int = 4) -> np.ndarray:
    half_w, half_h = out_w // 2, out_h // 2

    full = resize_rgba(src, half_w, half_h).astype(np.float64) / 255.0
    alpha = full[..., 3]
    # premultiply before the resize?  (already resized) — un-premultiply is not
    # needed here because Qt resizes RGBA with its own filtering; we only need
    # to keep fully transparent pixels from contributing colour.
    rgb = np.where(alpha[..., None] > 0, full[..., :3], 0.0)

    thr = np.tile(BAYER, (half_h // 4 + 1, half_w // 4 + 1))[:half_h, :half_w]
    t_rgb = thr[..., None] - 0.5
    t_a = thr - 0.5

    q = np.round(np.clip(rgb + t_rgb / (levels - 1), 0.0, 1.0) * (levels - 1)) / (levels - 1)
    qa = np.round(np.clip(alpha + t_a / (alpha_levels - 1), 0.0, 1.0) * (alpha_levels - 1)) / (alpha_levels - 1)

    out = np.concatenate([q, qa[..., None]], axis=2)
    out8 = (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    # 2x nearest-neighbour: every dither cell becomes a 2x2 block
    return np.repeat(np.repeat(out8, 2, axis=0), 2, axis=1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=str(SRC_DEFAULT))
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--height", type=int, default=288,
                    help="final height in raster pixels (rounded to even; default 288 "
                         "= largest that fits the boot screen's CRT safe area)")
    ap.add_argument("--cover", default="",
                    help="fill a target raster instead, e.g. 720x480: the art is "
                         "cropped to that aspect and covers the whole screen. "
                         "Matches the other UI backgrounds (dither grid 360x240).")
    ap.add_argument("--anchor", choices=("center", "top"), default="center",
                    help="which part of the art to keep when --cover crops it")
    args = ap.parse_args()

    src_path = Path(args.src)
    if not src_path.exists():
        print(f"source art not found: {src_path}")
        return 2

    src = trim(load_rgba(src_path)) if not args.cover else load_rgba(src_path)
    sh, sw = src.shape[:2]

    if args.cover:
        tw, th = (int(v) for v in args.cover.lower().split("x"))
        tw -= tw % 2
        th -= th % 2
        rows = round(sw * th / tw)
        if rows <= sh:
            y0 = 0 if args.anchor == "top" else (sh - rows) // 2
            crop = src[y0:y0 + rows]
        else:
            cols = round(sh * tw / th)
            x0 = (sw - cols) // 2
            crop = src[:, x0:x0 + cols]
        out = dither_rgba(crop, tw, th)
        save_rgba(out, Path(args.out))
        print(f"{Path(args.out).name}: {out.shape[1]}x{out.shape[0]} "
              f"(full-bleed cover, dither grid {tw // 2}x{th // 2}, 2x2 px cells)")
        return 0

    ratio = sw / sh
    out_h = args.height - (args.height % 2)
    out_w = round(out_h * ratio)
    out_w += out_w % 2

    out = dither_rgba(src, out_w, out_h)
    save_rgba(out, Path(args.out))
    print(f"{Path(args.out).name}: {out.shape[1]}x{out.shape[0]} "
          f"(dither grid {out_w // 2}x{out_h // 2}, 2x2 px cells, {6} levels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
