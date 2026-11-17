"""
base.py — BaseScreen + shared styling helpers for nullaOS v0.3

Per HANDOVER_UI.md:
  - Bedstead font (regular weight only, no italic). Family names:
      "Bedstead"     (standard width, advance 0.600 em)
      "Bedstead Extended"  (extended width, advance 0.744 em)
  - 13 design tokens (see palette section below)
  - 4:3 raster at 720×480, PAR 8:9 (pixels are ~11% narrower than tall)
      → circles must use width = height × 9/8 to look round on the Aiwa CRT
  - Drop shadow on every text (draw again at +2,+2 in rgba(0,0,0,.55))
    Bold emulation (Bedstead regular only): draw text again at +1 px x in same color
  - Min type 18 px; no horizontal strokes < 2 px; dither cells 2×2 px
  - No software CRT effects (real phosphor)

UI_FONT constant controls standard vs extended Bedstead. Default "Bedstead" (standard);
toggle to "Bedstead Extended" for the wider variant. Ask user to photograph the Aiwa
before locking this.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtGui import (
    QPainter, QLinearGradient, QColor, QFont, QFontDatabase, QPaintEvent,
    QPainterPath, QRadialGradient, QPixmap, QImage
)
from PySide6.QtWidgets import QWidget

# ── Project paths ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"
UI_DIR = PROJECT_ROOT / "assets" / "ui"

# ── Font choice ──────────────────────────────────────────────────────────────
# Default to standard Bedstead. Toggle at runtime by setting UI_FONT to
# "Bedstead Extended" — Qt will pick up the second family automatically
# because both OTFs were registered at app startup via load_fonts().
# Ask the user to photograph the Aiwa before locking this choice.
UI_FONT = "Bedstead"           # "Bedstead" | "Bedstead Extended"
UI_FONT_EXTENDED = "Bedstead Extended"

# ── CRT visible area (measured, v0.7.2) ─────────────────────────────────────
# The user drew a red box on `crt_calibration_720x480.png` photographed on the
# Aiwa: the line sits at x 21-24 / 689-692 and y 0-2 / 449-452, so everything
# except a few pixels at each edge is visible.  These are the *inner* edges with
# a 4 px inset, and every screen should place text/HUDs inside them.
# (The old 72..652 / 48..431 numbers were an early estimate and much too tight.)
SAFE_LEFT = 28
SAFE_RIGHT = 684
SAFE_TOP = 8
SAFE_BOTTOM = 444


def safe_rect() -> QRect:
    """The visible raster area as a QRect (for hit tests / clamping)."""
    return QRect(SAFE_LEFT, SAFE_TOP, SAFE_RIGHT - SAFE_LEFT, SAFE_BOTTOM - SAFE_TOP)


# ── Design tokens (from HANDOVER_UI.md §3) ──────────────────────────────────
INK         = "#06070B"    # near-black
NAVY        = "#0A1A55"    # panels, plates
BLUE        = "#3FA9F5"    # highlight, selection, progress
GOLD        = "#FFB000"    # accents, focus, chips
CREAM       = "#F4F2FF"    # boot logo plate
PHOSPHOR    = "#5CFF3A"    # DDR-card readouts
TIVO_RED    = "#A30000"    # Library bg
TIVO_RED_LIGHT = "#C51818"
TIVO_RED_DARK  = "#6F0000"

# Guide cells (DirecTV-style)
GUIDE_ROW_FILL    = "#04041F"
GUIDE_ROW_DIVIDER = "#2F6FD8"
GUIDE_ROW_BOTTOM  = "#1B3F9F"
GUIDE_CHAN_FILL   = "#1F4FC0"
GUIDE_CHAN_BOTTOM = "#14338A"
GUIDE_MOVIE_FILL  = "#3C1670"
GUIDE_FRAME_BLUE  = "#4A7DE0"

# Live bar (metal pill)
METAL_PILL_TOP    = "#EEF3EF"
METAL_PILL_MID    = "#8D9D94"
METAL_PILL_BOT    = "#4D5C53"
METAL_BORDER      = "#072040"
PROGRESS_TOP      = "#BFE6FF"
PROGRESS_MID      = "#3FA9F5"
PROGRESS_BOT      = "#1B6FC0"
PLATE_GOLD        = "#FFB000"
PLATE_CYAN        = "#38C8FF"
PLATE_BLUE        = "#2F64C4"
PLATE_BORDER      = "#1C3F8F"

# Menu (silver ovals)
SILVER_TOP    = "#F4F8FF"
SILVER_MID    = "#7F8FB0"
SILVER_BOT    = "#E3EBFA"
MENU_INNER_GOLD_TOP = "#8A7A1C"
MENU_INNER_GOLD_BOT = "#3D3A08"
MENU_INNER_GOLD_TXT = "#FFE27A"
MENU_INNER_BLUE_TOP = "#4A8FE0"
MENU_INNER_BLUE_BOT = "#14388F"
MENU_SHADOW   = "#02082A"
MENU_PIPES_DARK = "#02082A"
MENU_PIPES_LIGHT = "#C9D3E6"

# Picker
PICKER_THUMB_BORDER_DIM    = "#9BB7E8"
PICKER_THUMB_BORDER_BRIGHT = "#FFFFFF"
PICKER_NAME_FILL  = "#05143A"
PICKER_INFO_FILL  = "#F1F6FF"
PICKER_DESC_TOP   = "#173D86"
PICKER_DESC_BOT   = "#0D2A63"
PICKER_DESC_BORDER = "#DBE8FF"
PICKER_GREEN_CIRCLE = "#2FB04A"
PICKER_RED_CIRCLE   = "#D8353B"

# Browser / Library
LIBRARY_TYPE_SHOW   = GOLD            # gold square indicator
LIBRARY_TYPE_MOVIE  = "#3AD16A"       # green ellipse indicator
LIBRARY_SELECTED_BORDER = "#E6F4FF"

# Boot
BOOT_LOGO_DARKBLUE = "#26337F"
BOOT_CHIP_SELECTED_TEXT = "#14143C"

# Old palette kept for backward compat with existing screen code that hasn't
# been ported yet. Will be removed once all screens are on the new tokens.
BG_DARK        = INK
PANEL          = NAVY
HIGHLIGHT_BLUE = BLUE
TEXT_PRIMARY   = "#FFFFFF"
TEXT_DIM       = "#7C7C9A"
ACCENT_GOLD   = GOLD
AD_TAG_RED    = "#E50000"
PHOSPHOR_FONT = UI_FONT
WORDMARK_FONT = UI_FONT

# Text shadow spec — draw text twice: first at +2,+2 in rgba(0,0,0,.55),
# then in the main color. Skip shadow on light/gold fills.
TEXT_SHADOW_COLOR = QColor(0, 0, 0, 140)   # ~0.55 alpha
TEXT_SHADOW_OFFSET = (2, 2)


# ── Font loading ────────────────────────────────────────────────────────────

def load_fonts():
    """Call once at app startup. Loads Bedstead + Bedstead Extended OTFs.
    Both OTFs MUST be present in assets/fonts/ for the design to render
    correctly; if missing, Qt falls back to system monospace which will
    look wrong but won't crash."""
    if not FONTS_DIR.is_dir():
        return
    for ext in ("*.ttf", "*.otf"):
        for p in FONTS_DIR.glob(ext):
            QFontDatabase.addApplicationFont(str(p))


def ui_font(pixel_size: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    """Get a Bedstead font at the given pixel size. Use setPixelSize (not
    pointSize) so the size matches the prototype exactly on the 720×480 raster."""
    f = QFont(UI_FONT)
    f.setPixelSize(pixel_size)
    f.setWeight(weight)
    # NOTE: Previous versions set f.setStyleStrategy(QFont.PreferNoAntialias | QFont.NoAntialias)
    # but PySide6 6.12+ removed those enum names from QFont's top-level namespace.
    # Antialiasing is on by default which is fine for the Bedstead font on a CRT.
    return f


# ── Texture loader ──────────────────────────────────────────────────────────

_TEXTURE_CACHE: dict[str, QPixmap] = {}


def load_texture(name: str, fallback_color: Optional[str] = None) -> Optional[QPixmap]:
    """Load a pre-dithered PNG from assets/ui/. Returns None if missing.
    Result is cached so repeated calls are cheap.

    Textures are 720×480 (or 220×220 for porthole, 120×96 for thumbs).
    They're pre-dithered with Bayer 4×4 / 6 levels per channel — DO NOT
    apply smooth scaling; use Qt.FastTransformation if you must scale,
    and integer factors only.
    """
    if name in _TEXTURE_CACHE:
        return _TEXTURE_CACHE[name]
    path = UI_DIR / name
    if not path.exists():
        if fallback_color is not None:
            # Generate a flat color pixmap as fallback
            pm = QPixmap(720, 480)
            pm.fill(QColor(fallback_color))
        else:
            return None
    else:
        pm = QPixmap(str(path))
    _TEXTURE_CACHE[name] = pm
    return pm


def paint_texture(painter: QPainter, rect: QRect | QRectF, name: str,
                 fallback_color: str = NAVY):
    """Blit a pre-dithered texture into the given rect, 1:1 unscaled.
    If the texture is missing, fill with fallback_color."""
    pm = load_texture(name)
    if pm is None or pm.isNull():
        painter.fillRect(rect, QColor(fallback_color))
        return
    # Set no smooth scaling — textures are pre-dithered at exact 720×480
    old_hints = painter.renderHints()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
    painter.drawPixmap(rect, pm, pm.rect())
    painter.setRenderHints(old_hints)


# ── Geometry helpers ────────────────────────────────────────────────────────

def ellipse_rect(cx: int, cy: int, h: int) -> QRectF:
    """Return a QRectF for an ellipse that LOOKS round on the 4:3 CRT.
    The CRT's pixels are ~11% narrower than tall (PAR 8:9), so a "round"
    shape needs width = height × 9/8.

    Args:
        cx, cy: center of the ellipse (in raster px)
        h:      height in raster px

    Returns:
        QRectF positioned at the center, sized w=h*9/8 × h.
    """
    w = int(h * 9 / 8)
    return QRectF(cx - w // 2, cy - h // 2, w, h)


# ── Text drawing helper (shadow + bold emulation) ──────────────────────────

def draw_text(painter: QPainter, x: int, y: int, text: str,
              pixel_size: int, color: QColor | str,
              shadow: bool = True, bold: bool = False,
              font: Optional[QFont] = None):
    """Draw text with the spec's drop shadow and bold-emulation passes.

    Per HANDOVER_UI.md §3:
      - Shadow: draw the string again at +2,+2 px in rgba(0,0,0,.55) underneath.
        Omit on light/gold fills (set shadow=False).
      - "Bold" emulation (Bedstead regular only): draw the text a second time
        at +1 px x in the same colour, then the shadow pass.
        Used for headings, logo "OS", channel numbers.

    Args:
        x, y:        baseline position (top-left of text bounding box if you
                     use painter.drawText(rect, Qt.AlignLeft | Qt.AlignTop, ...))
        text:        the string to draw
        pixel_size:  font size in raster pixels (≥18 per CRT rule)
        color:       QColor or hex string for the main text color
        shadow:      whether to draw the drop shadow (default True)
        bold:        whether to emulate bold with +1px x redraw (default False)
        font:        optional pre-built QFont; if None, uses ui_font(pixel_size)
    """
    if isinstance(color, str):
        color = QColor(color)
    if font is None:
        font = ui_font(pixel_size)
    painter.setFont(font)

    # Bold emulation: redraw at +1 px x in the same color
    # (advances the rising edge by 1 output pixel, like teletext's own bold)
    if bold:
        painter.setPen(color)
        painter.drawText(x + 1, y, text)

    # Shadow pass (drawn underneath the main pass)
    if shadow:
        painter.setPen(TEXT_SHADOW_COLOR)
        sx, sy = TEXT_SHADOW_OFFSET
        painter.drawText(x + sx, y + sy, text)

    # Main pass
    painter.setPen(color)
    painter.drawText(x, y, text)


# ── Glow pre-rendering (cached) ──────────────────────────────────────────────
# Glow is OPTIONAL — requires numpy for the box blur. If numpy isn't
# installed, make_glow() returns None and paint_glow() silently skips the
# halo. The app is fully functional without glow; selected cells just lack
# the soft halo. Install numpy (`pip install numpy`) to enable glow.

_GLOW_CACHE: dict[str, "QImage"] = {}
_GLOW_NUMPY_AVAILABLE = None  # None = unknown, True/False after first probe


def _check_numpy() -> bool:
    """Probe whether numpy is importable. Cached."""
    global _GLOW_NUMPY_AVAILABLE
    if _GLOW_NUMPY_AVAILABLE is None:
        try:
            import numpy  # noqa: F401
            _GLOW_NUMPY_AVAILABLE = True
        except ImportError:
            _GLOW_NUMPY_AVAILABLE = False
            import logging
            logging.getLogger("base").info(
                "numpy not installed — glow halos will be skipped. "
                "Install with: pip install numpy"
            )
    return _GLOW_NUMPY_AVAILABLE


def make_glow(w: int, h: int, color: QColor, radius: int = 12,
              shape: str = "round") -> "QImage | None":
    """Pre-render a blurred glow shape to a QImage. Cache by (w,h,color,radius,shape).
    Blit under the shape with CompositionMode_Plus.

    Returns None if numpy isn't available — caller should handle by skipping
    the glow (the shape itself still renders fine).

    Args:
        w, h:    glow image dimensions (should be larger than the shape by 2×radius)
        color:   glow color
        radius:  blur radius in pixels
        shape:   "round" for ellipses/pills, "rect" for boxes
    """
    if not _check_numpy():
        return None

    import numpy as np
    key = f"{w}x{h}_{color.name()}_{radius}_{shape}"
    if key in _GLOW_CACHE:
        return _GLOW_CACHE[key]

    # Draw the shape at full opacity into a numpy array
    img = np.zeros((h, w, 4), dtype=np.uint8)
    cy, cx = h / 2, w / 2
    if shape == "round":
        # Ellipse — match PAR-corrected aspect (8:9 pixels → w/h = 9/8 for round)
        rx = w / 2 * 0.95
        ry = h / 2 * 0.95
        yy, xx = np.mgrid[:h, :w]
        mask = ((xx - cx) ** 2 / rx ** 2 + (yy - cy) ** 2 / ry ** 2) <= 1.0
    else:  # rect
        pad = 4
        mask = np.zeros((h, w), dtype=bool)
        mask[pad:h-pad, pad:w-pad] = True

    img[mask, 0] = color.red()
    img[mask, 1] = color.green()
    img[mask, 2] = color.blue()
    img[mask, 3] = 255

    # Box blur — separable, applied radius times for a Gaussian-like result.
    def box_blur(a, r):
        if r <= 0:
            return a
        # Horizontal pass
        pad = np.pad(a, ((0, 0), (r, r), (0, 0)), mode='edge')
        kernel = np.ones(r * 2 + 1) / (r * 2 + 1)
        h_out = np.zeros_like(a)
        for i, k in enumerate(kernel):
            h_out += pad[:, i:i + a.shape[1]] * k
        # Vertical pass
        pad = np.pad(h_out, ((r, r), (0, 0), (0, 0)), mode='edge')
        v_out = np.zeros_like(a)
        for i, k in enumerate(kernel):
            v_out += pad[i:i + a.shape[0]] * k
        return v_out

    img = box_blur(img.astype(np.float32), radius)
    img = np.clip(img, 0, 255).astype(np.uint8)

    # QImage expects bytes in BGRA on little-endian (default for Windows)
    qimg = QImage(img.tobytes(), w, h, w * 4, QImage.Format_RGBA8888)
    _GLOW_CACHE[key] = qimg
    return qimg


def paint_glow(painter: QPainter, x: int, y: int, w: int, h: int,
               color: QColor, radius: int = 12, shape: str = "round"):
    """Paint a pre-rendered glow at (x, y) with size (w, h). The glow is
    larger than the shape itself — pass w, h = shape_size + 2 * radius.

    Silently no-ops if numpy isn't available (glow halo will be missing
    but the shape itself still renders)."""
    glow = make_glow(w, h, color, radius, shape)
    if glow is None:
        return  # numpy not installed — skip glow, app still works
    painter.save()
    painter.setCompositionMode(QPainter.CompositionMode_Plus)
    painter.drawImage(x, y, glow)
    painter.restore()


# ── Legacy SkyBackground (kept for backward compat; prefer paint_sky_background) ──

_CLOUD_POSITIONS = [
    (0.10, 0.18, 0.18, 0.06),
    (0.55, 0.12, 0.22, 0.05),
    (0.78, 0.22, 0.14, 0.04),
    (0.25, 0.32, 0.20, 0.05),
    (0.65, 0.40, 0.16, 0.04),
]

SKY_TOP =        "#3D1F5C"
SKY_MID =        "#5A3F8F"
SKY_BOTTOM =     "#6B9BD8"
CLOUD_COLOR =    "#FFFFFF"
CLOUD_ALPHA =    80


def paint_sky_background(painter: QPainter, rect: QRect, draw_clouds: bool = True):
    """LEGACY sky gradient (procedural). Used as fallback when boot_sky.png
    is missing. For v0.3 the boot screen paints boot_sky.png instead."""
    grad = QLinearGradient(0, 0, 0, rect.height())
    grad.setColorAt(0.0, QColor(SKY_TOP))
    grad.setColorAt(0.45, QColor(SKY_MID))
    grad.setColorAt(1.0, QColor(SKY_BOTTOM))
    painter.fillRect(rect, grad)
    if draw_clouds:
        painter.setPen(Qt.NoPen)
        c = QColor(CLOUD_COLOR); c.setAlpha(CLOUD_ALPHA)
        painter.setBrush(c)
        for x_frac, y_frac, w_frac, h_frac in _CLOUD_POSITIONS:
            cx = int(rect.width() * x_frac)
            cy = int(rect.height() * y_frac)
            cw = int(rect.width() * w_frac)
            ch = int(rect.height() * h_frac)
            painter.drawEllipse(cx, cy, cw, ch)


class SkyBackground(QWidget):
    """DEPRECATED — use paint_sky_background() free function or
    paint_texture(painter, rect, 'boot_sky.png')."""
    def __init__(self, draw_clouds: bool = True, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._show_clouds = draw_clouds
        self.setAutoFillBackground(False)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        try:
            paint_sky_background(painter, self.rect(), draw_clouds=self._show_clouds)
        finally:
            painter.end()


# ── BaseScreen — common ancestor for all screens ────────────────────────────

class BaseScreen(QWidget):
    """Holds a back-reference to the MainWindow so screens can call
    router methods. Each screen overrides handle_input(action: str)."""

    def __init__(self, main_window: "MainWindow", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.main = main_window

    def handle_input(self, action: str):
        """Override in subclasses."""
        pass

    def on_show(self):
        """Called when this screen becomes active in the stack."""
        pass
