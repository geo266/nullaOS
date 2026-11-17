#!/usr/bin/env python3
"""Rebuild nullaOS UI textures: crop to 4:3, stretch to the 720x480 raster,
ordered-dither (Bayer 4x4, 6 levels/channel) at HALF resolution, upscale 2x nearest
so every dither cell is 2x2 px (>= 2 rows tall => no interlace flicker).
Usage: python tools/build_ui_assets.py [SRC_DIR] [OUT_DIR]
Needs: pillow numpy opencv-python-headless"""
import sys, numpy as np, cv2
from pathlib import Path
from PIL import Image
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else 'reference/sources')
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else 'assets/ui'); OUT.mkdir(parents=True, exist_ok=True)
BAY = np.array([[0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]]) / 16
def f(prefix): return next(SRC.glob(prefix + '*'))
def inpaint(im, rects, r=10):
    a = np.array(im.convert('RGB')); m = np.zeros(a.shape[:2], np.uint8)
    for x0, y0, x1, y1 in rects: m[y0:y1, x0:x1] = 255
    return Image.fromarray(cv2.inpaint(a, m, r, cv2.INPAINT_TELEA))
def vblur(im, n):  # kills baked 1-3px horizontal scanline textures
    a = np.asarray(im.convert('RGB'), float)
    for _ in range(n):
        p = np.pad(a, ((1,1),(0,0),(0,0)), mode='edge'); a = (p[:-2] + 2*p[1:-1] + p[2:]) / 4
    return Image.fromarray(a.astype('uint8'))
def crop43(im, fx=.5, fy=.5):
    w, h = im.size
    if w / h > 4 / 3: cw = round(h * 4 / 3); x = round((w - cw) * fx); return im.crop((x, 0, x + cw, h))
    ch = round(w * 3 / 4); y = round((h - ch) * fy); return im.crop((0, y, w, y + ch))
def dither(im, w, h, levels=6):  # w,h = HALF-res dither grid; output is 2w x 2h
    a = np.asarray(im.convert('RGB').resize((w, h), Image.LANCZOS), float) / 255
    t = np.tile(BAY, (h // 4 + 1, w // 4 + 1))[:h, :w, None] - .5
    q = np.round(np.clip(a + t / (levels - 1), 0, 1) * (levels - 1)) / (levels - 1)
    return Image.fromarray((q * 255).astype('uint8')).resize((w * 2, h * 2), Image.NEAREST)
def save(im, name): im.convert('RGB').save(OUT / name, optimize=True); print(name, im.size)
# boot: user's pre-dithered sky -> gradient map (keeps dither pattern) toward lavender
sk = Image.open(f('sky.png')).convert('RGB'); L = np.asarray(sk.convert('L'), float) / 255
st = np.array([[14,22,92],[66,72,168],[168,158,232]], float)
save(Image.fromarray(np.stack([np.interp(L, [0,.5,1], st[:,c]) for c in range(3)], -1).astype('uint8')), 'boot_sky.png')
# guide: paint out the baked "SENTIMIENTO INTIMO" pill
g = inpaint(Image.open(f('intimate_feeling')), [(116,344,274,384)], 14)
save(dither(crop43(g), 360, 240), 'guide_bg.png')
# channels: paint out baked title + frame lines, blur away scan texture
p = inpaint(Image.open(f('eliptical_detour')), [(64,592,540,668),(41,0,50,600),(180,655,1032,664),(180,655,188,774)], 12)
save(dither(crop43(vblur(p, 3)), 360, 240), 'picker_bg.png')
# menu: disc background (4:3 crop biased left)
save(dither(crop43(Image.open(f('dvd_player')), .08), 360, 240), 'menu_bg.png')
# menu porthole: glass-ring render, square crop around the big ring -> 220x220
b = Image.open(f('bryce_render')).convert('RGB'); save(dither(b.crop((247,10,727,490)), 110, 110), 'porthole.png')
# channel thumbnails 120x96 (index = catalog order)
for i, (pre, fx) in enumerate([('wetopia',.5),('primavera',.75),('ocean_of_cyber',.5),('warner_home',.5)]):
    save(dither(crop43(Image.open(f(pre)), fx), 60, 48), f'thumb_{i}.png')
