"""
browser.py — TiVo-style library list (v0.3.1)

Per HANDOVER_UI.md §5 Library + user feedback:
  - Bg: library_bg.png texture (NEW — was solid red radial gradient; user
    wanted something more interesting. Generated from harmony wallpaper via
    the same dither pipeline as other textures.)
  - Optional dark red overlay (rgba(80,0,0,80)) on top of the texture for
    the TiVo list feel without losing the texture detail.
  - Header at 40,22: antenna-TV SVG icon (white body, red screen, gold dot)
    + "Library" 42px
  - Rows x40…680, y = 96 + i*47, h44, r22, pad 18, title 28px
    Left icon area (40x44): if cover image exists, show it (cover-fit, 32x44);
                          else fall back to gold square (show) or green ellipse (movie)
    Right: weekday (22px, w60) + date (22px, w64)
    Selected = blue pill #3FA9F5, 3px #E6F4FF border,
              glow 0 0 14 rgba(63,169,245,.8)
  - Hint 22px centered at bottom margin 28
"""

from __future__ import annotations

from typing import Optional
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF, QTimer
from PySide6.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QPen, QRadialGradient, QPixmap,
)
from PySide6.QtWidgets import QWidget

from .base import (
    BaseScreen, draw_text, ellipse_rect, paint_glow, load_texture,
    NAVY, GOLD, BLUE, INK, TEXT_PRIMARY, TEXT_DIM,
    TIVO_RED, TIVO_RED_LIGHT, TIVO_RED_DARK,
    LIBRARY_TYPE_SHOW, LIBRARY_TYPE_MOVIE, LIBRARY_SELECTED_BORDER,
    UI_FONT,
)
from ..catalog import VideoItem, Library


# Cache for cover pixmaps — load once per path
_COVER_CACHE: dict[str, QPixmap] = {}


def _load_cover(path_str: str) -> Optional[QPixmap]:
    """Load a movie/show cover PNG, with caching. Returns None if missing."""
    if path_str in _COVER_CACHE:
        return _COVER_CACHE[path_str]
    # Resolve relative to project root
    project_root = Path(__file__).resolve().parent.parent.parent
    full_path = project_root / path_str
    if not full_path.exists():
        _COVER_CACHE[path_str] = None
        return None
    pm = QPixmap(str(full_path))
    if pm.isNull():
        _COVER_CACHE[path_str] = None
        return None
    _COVER_CACHE[path_str] = pm
    return pm


class BrowserScreen(BaseScreen):
    """TiVo-style library browser with textured background + movie covers."""

    # ── Title scroller (v0.6.1) ──────────────────────────────────────────
    # A title wider than its row scrolls while that row is selected, like a
    # stock ticker: 1.2 s still, then left at ~42 px/s, repeating with a gap.
    MARQUEE_SPEED = 42.0        # px per second
    MARQUEE_DELAY = 1.2         # seconds before it starts moving
    MARQUEE_GAP = 72            # px between the end of the title and its repeat

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)
        self.items: list[tuple[str, VideoItem]] = []
        self.selected_idx: int = 0
        self.scroll_offset: int = 0
        self.rows_visible: int = 7

        self._marquee_t = 0.0
        self._marquee_timer = QTimer(self)
        self._marquee_timer.setInterval(33)          # ~30 fps
        self._marquee_timer.timeout.connect(self._tick_marquee)

        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def on_show(self):
        self.items = self.main.catalog.library.all_items()
        self.selected_idx = 0
        self.scroll_offset = 0
        self._sync_marquee()
        self.update()

    def hideEvent(self, event):
        self._marquee_timer.stop()
        super().hideEvent(event)

    # ── Title scroller ───────────────────────────────────────────────

    def _title_geometry(self):
        """(x, width) of the title column — shared by paint and the scroller."""
        row_w = self.width() - 80
        title_x = 40 + 8 + 32 + 12        # row_x + icon box + gap
        title_w = row_w - 60 - 64 - 32 - 12
        return title_x, title_w

    def _selected_overflows(self) -> bool:
        if not (0 <= self.selected_idx < len(self.items)):
            return False
        _, item = self.items[self.selected_idx]
        fm = QFontMetrics(self._row_font())
        _, title_w = self._title_geometry()
        return fm.horizontalAdvance(item.title) > title_w

    def _row_font(self) -> QFont:
        f = QFont(UI_FONT)
        f.setPixelSize(28)
        return f

    def _sync_marquee(self):
        """Restart the scroller if the now-selected title doesn't fit."""
        self._marquee_t = 0.0
        if self._selected_overflows():
            if not self._marquee_timer.isActive():
                self._marquee_timer.start()
        else:
            self._marquee_timer.stop()

    def _tick_marquee(self):
        self._marquee_t += 0.033
        self.update()

    def _marquee_offset(self, fm: QFontMetrics, text: str) -> float:
        """Pixels to shift the title left (0 while the row still fits)."""
        _, title_w = self._title_geometry()
        text_w = fm.horizontalAdvance(text)
        if text_w <= title_w:
            return 0.0
        t = max(0.0, self._marquee_t - self.MARQUEE_DELAY)
        loop = text_w + self.MARQUEE_GAP
        return (t * self.MARQUEE_SPEED) % loop

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            w, h = self.width(), self.height()

            # ── Background: library_bg.png texture (with subtle red overlay) ─
            lib_tex = load_texture("library_bg.png")
            if lib_tex is not None and not lib_tex.isNull():
                painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                painter.drawPixmap(0, 0, lib_tex)
            else:
                # Fallback: radial gradient (original v0.3 design)
                grad = QRadialGradient(w / 2, h * 0.4, w * 0.7)
                grad.setColorAt(0.0, QColor(TIVO_RED_LIGHT))
                grad.setColorAt(0.6, QColor(TIVO_RED))
                grad.setColorAt(1.0, QColor(TIVO_RED_DARK))
                painter.fillRect(self.rect(), grad)

            # Subtle dark red overlay to retain the TiVo feel without
            # burying the texture
            painter.fillRect(self.rect(), QColor(80, 0, 0, 100))

            # ── Header (antenna-TV icon + "Library") ──────────────────────────
            self._draw_antenna_icon(painter, 40, 22, 58)

            title_font = QFont(UI_FONT); title_font.setPixelSize(42)
            painter.setFont(title_font)
            painter.setPen(QColor(0, 0, 0, 140))
            painter.drawText(QRectF(40 + 58 + 8 + 2, 22 + 2, w - 200, 58),
                              Qt.AlignVCenter | Qt.AlignLeft, "Library")
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(QRectF(40 + 58 + 8, 22, w - 200, 58),
                              Qt.AlignVCenter | Qt.AlignLeft, "Library")

            # ── Rows ───────────────────────────────────────────────────────────
            if not self.items:
                empty_font = QFont(UI_FONT); empty_font.setPixelSize(20)
                painter.setFont(empty_font)
                painter.setPen(QColor(TEXT_PRIMARY))
                msg = "Library is empty — drop files in assets/mock/library/"
                fm = QFontMetrics(empty_font)
                tw = fm.horizontalAdvance(msg)
                painter.drawText((w - tw) // 2, h // 2, msg)
                return

            row_h = 44
            row_y_start = 96
            row_gap = 47 - row_h
            row_x = 40
            row_w = w - 80

            if self.selected_idx < self.scroll_offset:
                self.scroll_offset = self.selected_idx
            elif self.selected_idx >= self.scroll_offset + self.rows_visible:
                self.scroll_offset = self.selected_idx - self.rows_visible + 1

            row_font = QFont(UI_FONT); row_font.setPixelSize(28)
            row_fm = QFontMetrics(row_font)

            for vis_i in range(self.rows_visible):
                data_i = self.scroll_offset + vis_i
                if data_i >= len(self.items):
                    break
                category, item = self.items[data_i]
                y = row_y_start + vis_i * 47
                row_rect = QRectF(row_x, y, row_w, row_h)
                is_sel = (data_i == self.selected_idx)

                # Glow for selected
                if is_sel:
                    paint_glow(painter,
                               x=row_x - 7, y=int(y) - 7,
                               w=row_w + 14, h=row_h + 14,
                               color=QColor(63, 169, 245, 200),
                               radius=10, shape="round")

                if is_sel:
                    painter.setPen(QPen(QColor(LIBRARY_SELECTED_BORDER), 3))
                    painter.setBrush(QColor(BLUE))
                    text_color = QColor("#FFFFFF")
                else:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(0, 0, 0, 120))   # darker pill over texture
                    text_color = QColor("#FFFFFF")

                painter.drawRoundedRect(row_rect, 22, 22)

                # ── Left icon: cover image if available, else type indicator ─
                icon_x = row_x + 8
                icon_w_box = 32   # cover thumbnail width
                icon_h_box = row_h - 4
                icon_y = y + 2
                icon_rect = QRectF(icon_x, icon_y, icon_w_box, icon_h_box)

                cover_pm = _load_cover(item.cover) if item.cover else None
                if cover_pm is not None and not cover_pm.isNull():
                    # Cover-fit: scale pixmap to fill icon_rect, crop overflow
                    painter.save()
                    clip_path = __import__("PySide6.QtGui",
                                            fromlist=["QPainterPath"]).QPainterPath()
                    clip_path.addRoundedRect(icon_rect, 4, 4)
                    painter.setClipPath(clip_path)
                    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                    # Cover-fit math
                    pm_w = cover_pm.width()
                    pm_h = cover_pm.height()
                    scale = max(icon_w_box / pm_w, icon_h_box / pm_h)
                    scaled_w = int(pm_w * scale)
                    scaled_h = int(pm_h * scale)
                    sx = int(icon_x - (scaled_w - icon_w_box) / 2)
                    sy = int(icon_y - (scaled_h - icon_h_box) / 2)
                    painter.drawPixmap(sx, sy, scaled_w, scaled_h, cover_pm)
                    painter.restore()
                    # Re-draw border
                    painter.setPen(QPen(QColor("#FFFFFF"), 1))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRoundedRect(icon_rect, 4, 4)
                else:
                    # Type indicator fallback (gold square for shows, green ellipse for movies)
                    indicator_y_center = y + row_h // 2
                    if item.kind == "s":
                        painter.setBrush(QColor(LIBRARY_TYPE_SHOW))
                        painter.setPen(Qt.NoPen)
                        painter.drawRoundedRect(
                            QRectF(icon_x + 4, indicator_y_center - 12, 24, 24),
                            4, 4)
                    else:
                        painter.setBrush(QColor(LIBRARY_TYPE_MOVIE))
                        painter.setPen(Qt.NoPen)
                        painter.drawEllipse(
                            QRectF(icon_x + 4, indicator_y_center - 12, 27, 24))

                # Title (28px) — pushed right to make room for cover thumbnail.
                # v0.6.1: if it doesn't fit, the SELECTED row scrolls it
                # instead of chopping the end off.
                painter.setFont(row_font)
                title_x = icon_x + icon_w_box + 12
                title_w = row_w - 60 - 64 - icon_w_box - 12

                if is_sel and row_fm.horizontalAdvance(item.title) > title_w:
                    self._paint_marquee_title(painter, row_fm, item.title,
                                              title_x, y, title_w, row_h, text_color)
                else:
                    painter.setPen(QColor(0, 0, 0, 140))
                    painter.drawText(QRectF(title_x + 2, y + 2, title_w, row_h),
                                      Qt.AlignVCenter | Qt.AlignLeft, item.title)
                    painter.setPen(text_color)
                    painter.drawText(QRectF(title_x, y, title_w, row_h),
                                      Qt.AlignVCenter | Qt.AlignLeft, item.title)

                # Right: weekday (22px, w60) + date (22px, w64)
                right_font = QFont(UI_FONT); right_font.setPixelSize(22)
                painter.setFont(right_font)
                # Weekday
                painter.setPen(QColor(0, 0, 0, 140))
                painter.drawText(QRectF(row_x + row_w - 124 - 2, y + 2, 60, row_h),
                                  Qt.AlignVCenter | Qt.AlignRight, item.added_day)
                painter.setPen(text_color)
                painter.drawText(QRectF(row_x + row_w - 124, y, 60, row_h),
                                  Qt.AlignVCenter | Qt.AlignRight, item.added_day)
                # Date
                painter.setPen(QColor(0, 0, 0, 140))
                painter.drawText(QRectF(row_x + row_w - 60 - 2, y + 2, 60, row_h),
                                  Qt.AlignVCenter | Qt.AlignRight, item.added_date)
                painter.setPen(text_color)
                painter.drawText(QRectF(row_x + row_w - 60, y, 60, row_h),
                                  Qt.AlignVCenter | Qt.AlignRight, item.added_date)

            # ── Footer hint ───────────────────────────────────────────────────
            hint_font = QFont(UI_FONT); hint_font.setPixelSize(22)
            painter.setFont(hint_font)
            painter.setPen(QColor(0, 0, 0, 140))
            painter.drawText(QRectF(0 + 2, 410 + 2, w, 22),
                              Qt.AlignCenter,
                              "Sorted by date added (press ENTER to open)")
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(QRectF(0, 410, w, 22),
                              Qt.AlignCenter,
                              "Sorted by date added (press ENTER to open)")
        finally:
            painter.end()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _paint_marquee_title(self, painter: QPainter, fm: QFontMetrics, text: str,
                             x: float, y: float, width: float, row_h: float,
                             color: QColor):
        """Scroll `text` left inside its column, repeating with a gap.

        Clipped to the title column so it never runs under the weekday/date,
        and drawn from an explicit baseline so the vertical centring is the
        same as the non-scrolling rows.
        """
        offset = self._marquee_offset(fm, text)
        text_w = fm.horizontalAdvance(text)
        loop = text_w + self.MARQUEE_GAP
        baseline = y + (row_h - fm.height()) / 2 + fm.ascent()

        painter.save()
        painter.setClipRect(QRectF(x, y, width, row_h))
        for dx in (0.0, loop):
            sx = x - offset + dx
            if sx > x + width or sx + text_w < x - loop:
                continue
            painter.setPen(QColor(0, 0, 0, 140))
            painter.drawText(QPointF(sx + 2, baseline + 2), text)
            painter.setPen(color)
            painter.drawText(QPointF(sx, baseline), text)
        painter.restore()

    def _draw_antenna_icon(self, painter: QPainter, x: int, y: int, size: int):
        """Draw the TiVo-style antenna-TV icon (white body, red screen, gold dot)."""
        scale = size / 58
        # Two antenna lines (white)
        pen = QPen(QColor("#FFFFFF"), 4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(int(x + 20 * scale), int(y + 12 * scale),
                          int(x + 14 * scale), int(y + 2 * scale))
        painter.drawLine(int(x + 38 * scale), int(y + 12 * scale),
                          int(x + 44 * scale), int(y + 2 * scale))

        # White body (rounded rect, 4,12,50,40, r10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        body = QRectF(x + 4 * scale, y + 12 * scale,
                       50 * scale, 40 * scale)
        painter.drawRoundedRect(body, 10 * scale, 10 * scale)

        # Red screen (rounded rect, 11,19,36,26, r6)
        painter.setBrush(QColor(TIVO_RED))
        screen = QRectF(x + 11 * scale, y + 19 * scale,
                         36 * scale, 26 * scale)
        painter.drawRoundedRect(screen, 6 * scale, 6 * scale)

        # Gold dot (circle 29,32,5)
        painter.setBrush(QColor(GOLD))
        painter.drawEllipse(QPointF(x + 29 * scale, y + 32 * scale), 5 * scale, 5 * scale)

    # ── Input ─────────────────────────────────────────────────────────────

    def handle_input(self, action: str):
        if not self.items:
            if action in ("back", "guide"):
                self.main.show_boot()
            return

        if action == "up":
            self.selected_idx = (self.selected_idx - 1) % len(self.items)
            self._sync_marquee()
            self.update()
        elif action == "down":
            self.selected_idx = (self.selected_idx + 1) % len(self.items)
            self._sync_marquee()
            self.update()
        elif action == "enter":
            if 0 <= self.selected_idx < len(self.items):
                _, item = self.items[self.selected_idx]
                self.main.play_library_item(item)
        elif action == "back":
            self.main.show_boot()
        elif action == "guide":
            self.main.enter_tv_mode()
        elif action == "play_pause":
            if self.main.player:
                self.main.player.pause()
