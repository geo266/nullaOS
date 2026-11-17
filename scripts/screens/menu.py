"""
menu.py — Octopussy DVD-style menu screen

Per HANDOVER_UI.md §5 Menu:
  - Bg = menu_bg.png (with fallback to radial gradient)
  - Four ovals at (40, 52+98*i, 300, 62):
      outer silver gradient r31, 5px pad, drop shadow 0 4 0 #02082A
      inner r26 gradient #8A7A1C→#3D3A08, 26px #FFE27A + 2px black shadow
      selected inner = #4A8FE0→#14388F, white text
  - Items: SETTINGS · THEMES · LIBRARY · ABOUT (LIBRARY → Library screen)
  - Silver pipes (draw under the porthole):
      for item i, polyline (340, 83+98i) → (400, same) → (400, 210+30i) → (462, same)
      stroke 10px #02082A, then 6px #C9D3E6
  - Porthole: ellipse 438,130,258,230 (9:8-corrected), silver rim 14px,
    interior = porthole.png (cover) with inner shadow
  - Top-right three gold dots (29x26, gap 12, right margin 40, top 24);
    the third shows the major version ("3")
"""

from __future__ import annotations

import datetime
from typing import Optional

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QPen, QLinearGradient, QRadialGradient,
    QPixmap, QPainterPath, QMovie,
)
from PySide6.QtWidgets import QWidget

from .base import (
    BaseScreen, paint_texture, draw_text, ellipse_rect, load_texture, PROJECT_ROOT,
    SILVER_TOP, SILVER_MID, SILVER_BOT,
    MENU_INNER_GOLD_TOP, MENU_INNER_GOLD_BOT, MENU_INNER_GOLD_TXT,
    MENU_INNER_BLUE_TOP, MENU_INNER_BLUE_BOT,
    MENU_SHADOW, MENU_PIPES_DARK, MENU_PIPES_LIGHT,
    GOLD, TEXT_PRIMARY, INK, NAVY, UI_FONT,
)
from ..version import APP_VERSION


MENU_ITEMS = [
    ("SETTINGS", "settings"),
    ("THEMES",   "themes"),
    ("LIBRARY",  "library"),
    ("ABOUT",    "about"),
]


class MenuScreen(BaseScreen):
    """Octopussy-style DVD menu with silver ovals + porthole."""

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)
        self.selected_idx = 0
        self._notice = ""
        self._notice_until = 0.0
        # v0.7.0: the porthole is the user's animated GIF (green wireframe
        # globe) instead of the static porthole.png, and it no longer prints a
        # channel number inside it.
        self._movie: Optional[QMovie] = None
        gif = PROJECT_ROOT / "assets" / "ui" / "porthole.gif"
        if gif.exists():
            movie = QMovie(str(gif))
            if movie.isValid():
                movie.frameChanged.connect(self.update)
                movie.start()
                self._movie = movie
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def _set_notice(self, text: str):
        self._notice = text
        self._notice_until = datetime.datetime.now().timestamp() + 2.5
        self.update()
        QTimer.singleShot(2600, self.update)

    def on_show(self):
        self.selected_idx = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            w, h = self.width(), self.height()

            # ── Background texture (menu_bg.png) ────────────────────────────
            menu_tex = load_texture("menu_bg.png")
            if menu_tex is not None and not menu_tex.isNull():
                painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                painter.drawPixmap(0, 0, menu_tex)
            else:
                # Fallback: radial gradient per CSS
                grad1 = QRadialGradient(w / 2, 0, w)
                grad1.setColorAt(0.0, QColor("#2250C8"))
                grad1.setColorAt(1.0, QColor(34, 80, 200, 0))
                painter.fillRect(self.rect(), QColor("#06134A"))
                painter.fillRect(self.rect(), grad1)
                grad2 = QRadialGradient(w / 2, h, w)
                grad2.setColorAt(0.0, QColor("#2250C8"))
                grad2.setColorAt(1.0, QColor(34, 80, 200, 0))
                painter.fillRect(self.rect(), grad2)

            # ── Silver pipes (draw under ovals and porthole) ─────────────────
            for i in range(len(MENU_ITEMS)):
                y = 83 + i * 98
                py = 210 + i * 30
                # Dark stroke (10px)
                pen_dark = QPen(QColor(MENU_PIPES_DARK), 10)
                pen_dark.setJoinStyle(Qt.RoundJoin)
                pen_dark.setCapStyle(Qt.RoundCap)
                painter.setPen(pen_dark)
                path = QPainterPath()
                path.moveTo(340, y)
                path.lineTo(400, y)
                path.lineTo(400, py)
                path.lineTo(462, py)
                painter.drawPath(path)
                # Light stroke (6px)
                pen_light = QPen(QColor(MENU_PIPES_LIGHT), 6)
                pen_light.setJoinStyle(Qt.RoundJoin)
                pen_light.setCapStyle(Qt.RoundCap)
                painter.setPen(pen_light)
                painter.drawPath(path)

            # ── Four ovals ────────────────────────────────────────────────────
            for i, (label, action) in enumerate(MENU_ITEMS):
                oval_x = 40
                oval_y = 52 + i * 98
                oval_w = 300
                oval_h = 62
                is_sel = (i == self.selected_idx)

                # Drop shadow (under outer)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(MENU_SHADOW))
                shadow_rect = QRectF(oval_x, oval_y + 4, oval_w, oval_h)
                painter.drawRoundedRect(shadow_rect, 31, 31)

                # Outer silver gradient
                outer_grad = QLinearGradient(oval_x, oval_y, oval_x, oval_y + oval_h)
                outer_grad.setColorAt(0.0, QColor(SILVER_TOP))
                outer_grad.setColorAt(0.5, QColor(SILVER_MID))
                outer_grad.setColorAt(1.0, QColor(SILVER_BOT))
                painter.setBrush(outer_grad)
                painter.setPen(Qt.NoPen)
                outer_rect = QRectF(oval_x, oval_y, oval_w, oval_h)
                painter.drawRoundedRect(outer_rect, 31, 31)

                # 5px pad → inner oval
                pad = 5
                inner_x = oval_x + pad
                inner_y = oval_y + pad
                inner_w = oval_w - pad * 2
                inner_h = oval_h - pad * 2
                inner_rect = QRectF(inner_x, inner_y, inner_w, inner_h)

                if is_sel:
                    inner_grad = QLinearGradient(inner_x, inner_y,
                                                  inner_x, inner_y + inner_h)
                    inner_grad.setColorAt(0.0, QColor(MENU_INNER_BLUE_TOP))
                    inner_grad.setColorAt(1.0, QColor(MENU_INNER_BLUE_BOT))
                    text_color = QColor("#FFFFFF")
                else:
                    inner_grad = QLinearGradient(inner_x, inner_y,
                                                  inner_x, inner_y + inner_h)
                    inner_grad.setColorAt(0.0, QColor(MENU_INNER_GOLD_TOP))
                    inner_grad.setColorAt(1.0, QColor(MENU_INNER_GOLD_BOT))
                    text_color = QColor(MENU_INNER_GOLD_TXT)

                painter.setBrush(inner_grad)
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(inner_rect, 26, 26)

                # Label text 26px, centered — 2px black shadow underneath
                label_font = QFont(UI_FONT)
                label_font.setPixelSize(26)
                painter.setFont(label_font)
                # Shadow
                painter.setPen(QColor(0, 0, 0))
                painter.drawText(inner_rect.adjusted(2, 2, 0, 0),
                                  Qt.AlignCenter, label)
                # Main
                painter.setPen(text_color)
                painter.drawText(inner_rect, Qt.AlignCenter, label)

            # ── Porthole (right side) ───────────────────────────────────────────
            # 9:8-corrected ellipse: 230 tall → 258 wide
            pole_w = 258
            pole_h = 230
            pole_x = 426
            pole_y = 130
            pole_rect = QRectF(pole_x, pole_y, pole_w, pole_h)

            # Silver rim (14px)
            rim_grad = QLinearGradient(pole_x, pole_y, pole_x + pole_w, pole_y + pole_h)
            rim_grad.setColorAt(0.0, QColor(SILVER_TOP))
            rim_grad.setColorAt(0.5, QColor(SILVER_MID))
            rim_grad.setColorAt(1.0, QColor("#DBE4F6"))
            painter.setPen(QPen(Qt.NoPen))   # no pen
            painter.setBrush(rim_grad)
            painter.drawEllipse(pole_rect)

            # Inner porthole (14px rim → inner ellipse)
            rim_w = 14
            inner_pole = pole_rect.adjusted(rim_w, rim_w, -rim_w, -rim_w)
            painter.setBrush(QColor("#000000"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(inner_pole)

            # Porthole.png / animated GIF (cover-fit)
            porthole_tex = load_texture("porthole.png")
            movie_frame = None
            if self._movie is not None:
                movie_frame = self._movie.currentPixmap()

            if (movie_frame is not None and not movie_frame.isNull()) or \
                    (porthole_tex is not None and not porthole_tex.isNull()):
                painter.save()
                clip_path = QPainterPath()
                clip_path.addEllipse(inner_pole)
                painter.setClipPath(clip_path)
                painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                if movie_frame is not None and not movie_frame.isNull():
                    painter.drawPixmap(inner_pole, movie_frame, movie_frame.rect())
                else:
                    painter.drawPixmap(inner_pole, porthole_tex, porthole_tex.rect())
                painter.restore()
            else:
                # Fallback: radial gold gradient per CSS
                grad = QRadialGradient(inner_pole.center().x() - inner_pole.width() * 0.15,
                                        inner_pole.center().y() - inner_pole.height() * 0.20,
                                        inner_pole.width() * 0.7)
                grad.setColorAt(0.0, QColor("#D8C24A"))
                grad.setColorAt(0.7, QColor("#6B5C0E"))
                grad.setColorAt(1.0, QColor("#000000"))
                painter.setBrush(grad)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(inner_pole)

            # ── Three gold dots top-right (29x26 each, gap 12) ─────────────────
            dot_w, dot_h = 29, 26
            dot_gap = 12
            dot_right_margin = 40
            dot_y = 24
            dot_labels = ["", "", APP_VERSION.split(".")[1]]   # minor version
            for i in range(3):
                dx = w - dot_right_margin - (3 - i) * (dot_w + dot_gap) - dot_w + (dot_w + dot_gap)
                # Simpler: position from right
                dx = w - dot_right_margin - (3 - i) * (dot_w + dot_gap) - dot_w + (dot_w + dot_gap) - dot_w
                # Actually let me recompute cleanly:
                # dot 0 is leftmost, dot 2 is rightmost (closest to right edge)
                # right edge of dot 2 = w - 40
                # right edge of dot 1 = right of dot 2 + gap + dot_w
                # ...nope, easier: dot i (0-indexed from left) has its right edge at
                # (w - 40) - (2 - i) * (dot_w + dot_gap)
                # and its left edge = right - dot_w
                dot_right = w - dot_right_margin - (2 - i) * (dot_w + dot_gap)
                dot_left = dot_right - dot_w
                # 9:8 PAR correction — make width = h * 9/8 to look round
                dot_h_corrected = int(dot_w * 8 / 9)
                dot_y_centered = dot_y + (dot_h - dot_h_corrected) // 2
                dot_rect = QRectF(dot_left, dot_y_centered, dot_w, dot_h_corrected)

                painter.setBrush(QColor("#FFD93A"))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(dot_rect)

                # Label (only for the third dot, shows "3")
                if dot_labels[i]:
                    lbl_font = QFont(UI_FONT)
                    lbl_font.setPixelSize(18)
                    painter.setFont(lbl_font)
                    painter.setPen(QColor("#14143C"))
                    painter.drawText(dot_rect, Qt.AlignCenter, dot_labels[i])

            # ── Transient notice (v0.7.0) ────────────────────────────────────
            if self._notice and datetime.datetime.now().timestamp() < self._notice_until:
                painter.setFont(QFont(UI_FONT, 18))
                painter.setPen(QColor(0, 0, 0, 180))
                painter.drawText(QRectF(40, 414, 640, 26), Qt.AlignCenter, self._notice)
                painter.setPen(QColor("#8CFF7A"))
                painter.drawText(QRectF(40, 412, 640, 26), Qt.AlignCenter, self._notice)
        finally:
            painter.end()

    # ── Input ─────────────────────────────────────────────────────────────

    def handle_input(self, action: str):
        if action == "up":
            self.selected_idx = (self.selected_idx - 1) % len(MENU_ITEMS)
            self.update()
        elif action == "down":
            self.selected_idx = (self.selected_idx + 1) % len(MENU_ITEMS)
            self.update()
        elif action == "enter":
            label, target = MENU_ITEMS[self.selected_idx]
            if target == "library":
                self.main.enter_browser_mode()
            elif target == "settings":
                self.main.show_settings()
            elif target == "themes":
                self._set_notice("NO OTHER THEMES INSTALLED")
            elif target == "about":
                from ..version import APP_NAME
                n = len(getattr(self.main.catalog, "channels", []))
                self._set_notice(f"{APP_NAME} v{APP_VERSION}   {n} CHANNELS")
        elif action in ("back", "menu"):
            # v0.7.0: return to whatever opened the menu (boot, guide, browser
            # or live) — the menu is no longer a one-way trip from Live.
            self.main.close_menu()
