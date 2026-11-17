"""
boot.py — nullaOS boot screen (v0.5.3)

Per user request: tightened vertical spacing between MEDIA EXPLORER → chips → version,
and used the freed space to make the logo ~40% bigger.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QPen, QLinearGradient, QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from .base import (
    BaseScreen, paint_texture, paint_sky_background, draw_text, ellipse_rect,
    load_texture,
    GOLD, CREAM, NAVY, INK, BLUE, TEXT_PRIMARY, TEXT_DIM, TEXT_SHADOW_COLOR,
    BOOT_LOGO_DARKBLUE, BOOT_CHIP_SELECTED_TEXT,
    UI_FONT,
)
from ..version import APP_VERSION


class BootScreen(BaseScreen):
    """nullaOS boot screen with sky texture + mode toggle."""

    # v0.5.3: Tightened spacing → bigger logo.
    # Logo box: 320×316 (was 240×224 — ~40% bigger)
    # Gaps reduced: logo→MEDIA EXPLORER 6px (was 28px),
    #               MEDIA EXPLORER→chips 16px (was 52px),
    #               chips→footer 16px (was 56px).
    LOGO_TOP = 40
    LOGO_BOX_W = 320
    LOGO_BOX_H = 316

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)
        self.selected_mode = "tv"
        self._boot_logo_pm = None
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def _boot_logo(self):
        if self._boot_logo_pm is None:
            pm = load_texture("boot_logo.png")
            if pm is not None and not pm.isNull():
                self._boot_logo_pm = pm.scaled(self.LOGO_BOX_W, self.LOGO_BOX_H,
                                               Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation)
        return self._boot_logo_pm

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            w, h = self.width(), self.height()

            # ── Sky background ──────────────────────────────────────────────
            sky_tex = load_texture("boot_sky.png")
            if sky_tex is not None and not sky_tex.isNull():
                painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                painter.drawPixmap(0, 0, sky_tex)
            else:
                paint_sky_background(painter, self.rect(), draw_clouds=True)

            # ── "TUNE IN:" header ─────────────────────────────────────────────
            header_font = QFont(UI_FONT)
            header_font.setPixelSize(28)
            fm_h = QFontMetrics(header_font)
            header_text = "TUNE IN:"
            tw = fm_h.horizontalAdvance(header_text)
            draw_text(painter,
                      x=(w - tw) // 2, y=33,
                      text=header_text,
                      pixel_size=28, color=GOLD,
                      shadow=False, bold=False,
                      font=header_font)

            # ── Logo: media-collage artboard (scaled bigger in v0.5.3) ──────
            logo_pm = self._boot_logo()
            if logo_pm is not None:
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.drawPixmap((w - logo_pm.width()) // 2,
                                   self.LOGO_TOP + (self.LOGO_BOX_H - logo_pm.height()) // 2,
                                   logo_pm)
            else:
                wordmark_font = QFont(UI_FONT)
                wordmark_font.setPixelSize(64)
                fm_wm = QFontMetrics(wordmark_font)
                wm_text = "nullaOS"
                tw_wm = fm_wm.horizontalAdvance(wm_text)
                draw_text(painter, x=(w - tw_wm) // 2, y=180, text=wm_text,
                          pixel_size=64, color=BOOT_LOGO_DARKBLUE,
                          shadow=True, bold=False, font=wordmark_font)

            # ── "MEDIA EXPLORER" — tightened gap (was 28px, now 6px) ────────
            sub_font = QFont(UI_FONT)
            sub_font.setPixelSize(30)
            sub_fm = QFontMetrics(sub_font)
            sub_text = "MEDIA EXPLORER"
            gap = 4
            char_widths = [sub_fm.horizontalAdvance(ch) for ch in sub_text]
            total_w_sub = sum(char_widths) + gap * (len(sub_text) - 1)
            x = (w - total_w_sub) // 2
            y_sub = self.LOGO_TOP + self.LOGO_BOX_H + 6  # 362
            for ch, cw in zip(sub_text, char_widths):
                draw_text(painter, x=x, y=y_sub, text=ch,
                          pixel_size=30, color=TEXT_PRIMARY,
                          shadow=True, bold=False, font=sub_font)
                x += cw + gap

            # ── TV/BROWSER chips — tightened gap (was 52px, now 16px) ────────
            chips_y = y_sub + 16  # 378
            chip_h = 36
            chip_pad_x = 22
            chip_pad_y = 2
            chip_gap = 16
            chip_text_size = 24
            chip_radius = 26

            chip_font = QFont(UI_FONT)
            chip_font.setPixelSize(chip_text_size)
            chip_fm = QFontMetrics(chip_font)
            tv_label = "TV"
            browser_label = "BROWSER"
            tv_w_ch = chip_fm.horizontalAdvance(tv_label)
            br_w_ch = chip_fm.horizontalAdvance(browser_label)
            chip_w_tv = tv_w_ch + chip_pad_x * 2 + 6
            chip_w_br = br_w_ch + chip_pad_x * 2 + 6
            total_chips_w = chip_w_tv + chip_gap + chip_w_br
            chips_x_start = (w - total_chips_w) // 2

            for i, (mode, label, chip_w) in enumerate([
                ("tv", tv_label, chip_w_tv),
                ("browser", browser_label, chip_w_br),
            ]):
                cx = chips_x_start + (chip_w_tv + chip_gap) * i
                cy = chips_y
                is_selected = (mode == self.selected_mode)
                rect = QRectF(cx, cy, chip_w, chip_h)

                if is_selected:
                    painter.setBrush(QColor(GOLD))
                    painter.setPen(QPen(QColor(GOLD), 3))
                    text_color = QColor(BOOT_CHIP_SELECTED_TEXT)
                else:
                    painter.setBrush(QColor(0, 0, 0, 0))
                    painter.setPen(QPen(QColor(TEXT_PRIMARY), 3))
                    text_color = QColor(TEXT_PRIMARY)

                painter.drawRoundedRect(rect, chip_radius, chip_radius)
                painter.setFont(chip_font)
                painter.setPen(text_color)
                painter.drawText(rect, Qt.AlignCenter, label)

            # ── Footer: version — tightened gap (was 56px, now 16px) ─────────
            footer_font = QFont(UI_FONT)
            footer_font.setPixelSize(24)
            footer_fm = QFontMetrics(footer_font)
            footer_text = f"v{APP_VERSION}"
            fw = footer_fm.horizontalAdvance(footer_text)
            draw_text(painter,
                      x=(w - fw) // 2, y=chips_y + chip_h + 24,  # 438, 5 px below the chips
                      text=footer_text,
                      pixel_size=24, color=GOLD,
                      shadow=False, bold=False,
                      font=footer_font)
        finally:
            painter.end()

    def handle_input(self, action: str):
        if action == "left":
            self.selected_mode = "tv"
            self.update()
        elif action == "right":
            self.selected_mode = "browser"
            self.update()
        elif action in ("up", "down"):
            self.selected_mode = "browser" if self.selected_mode == "tv" else "tv"
            self.update()
        elif action == "enter":
            if self.selected_mode == "tv":
                self.main.enter_tv_mode()
            else:
                self.main.enter_browser_mode()
        elif action == "quit":
            self.main.close()
        elif action == "guide":
            self.main.enter_tv_mode()
        elif action == "vault":
            self.main.enter_browser_mode()

    def on_show(self):
        self.selected_mode = "tv"
        self.update()
