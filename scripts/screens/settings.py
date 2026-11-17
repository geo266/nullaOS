"""
settings.py — the SETTINGS screen (opened from the M menu)

What lives here (v0.7.0):

  * CLOCK      — the app's own clock, VCR-style: set the hour and minute, the
                 whole broadcast day moves with it.  The guide and the schedule
                 read this clock, so this is also how you test dayparts.
  * TIME FORMAT— 24-hour or 12-hour readouts (guide, OSD).
  * COMMERCIALS— generate ad pods or not (rebuilds every timeline).
  * AUDIO LEVEL— VLC's volume normaliser, the "level the ads out" switch
                 (takes effect on the next launch: it is an instance option).
  * VOLUME     — the output level, with the same OSD as the volume keys.
  * HOTKEYS    — rebind any action to any key, stored in settings.json.
  * ABOUT      — version, channel count, where the catalog is.

Navigation: up/down = row, left/right = change, enter = edit / open,
back = leave (and the sub-screens return here).
"""

from __future__ import annotations

import datetime
from typing import Optional

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .base import (
    BaseScreen, draw_text, load_texture, GOLD, UI_FONT,
)
from ..version import APP_NAME, APP_VERSION

ROW_H = 42
LIST_TOP = 104
LABEL_X = 56
VALUE_RIGHT = 664

#: Actions that can be rebound, in menu order, with a human label.
HOTKEY_ACTIONS = [
    ("up", "CHANNEL / LIST UP"),
    ("down", "CHANNEL / LIST DOWN"),
    ("left", "LEFT"),
    ("right", "RIGHT"),
    ("enter", "SELECT"),
    ("back", "BACK"),
    ("play_pause", "PAUSE"),
    ("guide", "TV GUIDE"),
    ("menu", "MENU"),
    ("info", "INFO CARD"),
    ("vault", "LIBRARY"),
    ("picker", "CHANNEL PICKER"),
    ("vol_up", "VOLUME UP"),
    ("vol_down", "VOLUME DOWN"),
    ("aspect", "ASPECT (THIS FILE)"),
    ("crop", "CROP (THIS FILE)"),
]


def key_name(key: int) -> str:
    """'Up', 'Space', 'Plus' — what a QKeySequence calls it."""
    if not key:
        return "—"
    text = QKeySequence(int(key)).toString()
    return text.upper() if text else f"0x{int(key):X}"


class SettingsScreen(BaseScreen):
    """The settings list, plus the hotkey sub-list."""

    def __init__(self, main_window, parent: Optional[QWidget] = None):
        super().__init__(main_window, parent)
        self.selected = 0
        self.mode = "rows"            # "rows" | "hotkeys"
        self.hotkey_idx = 0
        self.editing_clock = False
        self.clock_field = 0          # 0 = hour, 1 = minute
        self.capturing_key = False
        self.notice = ""
        self.notice_until = 0.0
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    # ── state ─────────────────────────────────────────────────────────────

    @property
    def rows(self):
        """(key, label) for the main list — built each paint (cheap)."""
        return [
            ("clock", "CLOCK"),
            ("format", "TIME FORMAT"),
            ("ads", "COMMERCIALS"),
            ("audio", "AUDIO LEVELING"),
            ("volume", "VOLUME"),
            ("hotkeys", "HOTKEYS"),
            ("about", "ABOUT"),
        ]

    def on_show(self):
        self.mode = "rows"
        self.editing_clock = False
        self.capturing_key = False
        self.selected = min(self.selected, len(self.rows) - 1)
        self.update()

    def _set_notice(self, text: str):
        self.notice = text
        self.notice_until = datetime.datetime.now().timestamp() + 2.5
        self.update()

    # ── clock helpers ─────────────────────────────────────────────────────

    def _clock_parts(self) -> tuple[int, int]:
        now = self.main.clock.local()
        return now.hour, now.minute

    def _apply_clock(self):
        hh, mm = self._clock_parts()
        self.main.clock.set_wall(hh, mm, 0)
        self._set_notice(f"CLOCK SET TO {self._clock_text()}")

    def _clock_text(self) -> str:
        use24 = bool(self.main.settings.get("clock_24h", True))
        return self.main.clock.format_time(use_24h=use24, seconds=False)

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            self._paint_background(painter)
            if self.mode == "hotkeys":
                self._paint_hotkeys(painter)
            else:
                self._paint_rows(painter)
            self._paint_notice(painter)
        finally:
            painter.end()

    def _paint_background(self, painter: QPainter):
        w, h = self.width(), self.height()
        tex = load_texture("menu_bg.png")
        if tex is not None and not tex.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
            painter.drawPixmap(0, 0, tex)
        painter.fillRect(self.rect(), QColor(3, 6, 24, 190))

        painter.setPen(QPen(QColor("#1C3F8F"), 3))
        painter.setBrush(QColor(4, 8, 32, 225))
        painter.drawRect(QRectF(32, 24, w - 64, h - 48))

        draw_text(painter, 56, 52, "SETTINGS", 30, GOLD, shadow=False, bold=True)
        painter.setPen(QColor("#8FA8D8"))
        painter.setFont(self._font(16))
        painter.drawText(QRectF(56, 62, 600, 20), Qt.AlignLeft | Qt.AlignVCenter,
                         "UP/DOWN ROW    LEFT/RIGHT CHANGE    ENTER EDIT")

    def _font(self, px: int) -> QFont:
        f = QFont(UI_FONT)
        f.setPixelSize(px)
        return f

    def _value_text(self, key: str) -> str:
        s = self.main.settings
        if key == "clock":
            return self._clock_text()
        if key == "format":
            return "24-HOUR" if s.get("clock_24h", True) else "12-HOUR"
        if key == "ads":
            return "ON" if s.get("ads_enabled", True) else "OFF"
        if key == "audio":
            return "ON" if s.get("audio_leveling", True) else "OFF"
        if key == "volume":
            return f"{int(self.main.volume):d}%"
        if key == "hotkeys":
            return ">"
        if key == "about":
            n = len(getattr(self.main.catalog, "channels", []))
            return f"v{APP_VERSION}   {n} CH"
        return ""

    def _paint_rows(self, painter: QPainter):
        w = self.width()
        for i, (key, label) in enumerate(self.rows):
            y = LIST_TOP + i * ROW_H
            sel = (i == self.selected)
            row = QRectF(44, y, w - 88, ROW_H - 6)

            if sel:
                painter.setPen(QPen(QColor("#FFE08A"), 3))
                painter.setBrush(QColor(GOLD))
                painter.drawRoundedRect(row, 8, 8)
                color = QColor("#14143C")
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(2, 10, 40, 160))
                painter.drawRoundedRect(row, 8, 8)
                color = QColor("#D8E4FF")

            painter.setFont(self._font(22))
            painter.setPen(color)
            painter.drawText(QRectF(row.x() + 16, row.y(), 300, row.height()),
                             Qt.AlignVCenter | Qt.AlignLeft, label)

            value = self._value_text(key)
            painter.setFont(self._font(22))
            painter.drawText(QRectF(row.x() + 300, row.y(), row.width() - 316, row.height()),
                             Qt.AlignVCenter | Qt.AlignRight, value)

            # the clock being edited: underline the field
            if key == "clock" and sel and self.editing_clock:
                fm = QFontMetrics(self._font(22))
                vw = fm.horizontalAdvance(value)
                vx = row.right() - 16 - vw
                colon = value.find(":")
                if self.clock_field == 0:
                    start, length = 0, max(1, colon)
                else:
                    start, length = colon + 1, 2
                px = vx + fm.horizontalAdvance(value[:start])
                pw = fm.horizontalAdvance(value[start:start + length])
                painter.setPen(QPen(QColor("#14143C"), 3))
                painter.drawLine(int(px), int(row.bottom() - 7),
                                 int(px + pw), int(row.bottom() - 7))

    def _paint_hotkeys(self, painter: QPainter):
        w = self.width()
        draw_text(painter, 56, 52, "HOTKEYS", 30, GOLD, shadow=False, bold=True)
        painter.setPen(QColor("#8FA8D8"))
        painter.setFont(self._font(16))
        painter.drawText(QRectF(200, 30, 460, 24), Qt.AlignRight | Qt.AlignVCenter,
                         "ENTER TO REBIND   BACK TO RETURN")

        top = 88
        row_h = 26
        visible = 13
        first = max(0, min(self.hotkey_idx - visible // 2,
                           len(HOTKEY_ACTIONS) - visible))
        for vis, i in enumerate(range(first, min(len(HOTKEY_ACTIONS), first + visible))):
            action, label = HOTKEY_ACTIONS[i]
            y = top + vis * row_h
            sel = (i == self.hotkey_idx)
            row = QRectF(44, y, w - 88, row_h - 2)
            if sel:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(GOLD))
                painter.drawRoundedRect(row, 6, 6)
                color = QColor("#14143C")
            else:
                color = QColor("#D8E4FF")
            painter.setFont(self._font(18))
            painter.setPen(color)
            painter.drawText(QRectF(row.x() + 12, row.y(), 420, row.height()),
                             Qt.AlignVCenter | Qt.AlignLeft, label)
            key = self.main.input.key_map.get(action, 0)
            text = "PRESS A KEY…" if (sel and self.capturing_key) else key_name(key)
            painter.drawText(QRectF(row.x() + 420, row.y(), row.width() - 432, row.height()),
                             Qt.AlignVCenter | Qt.AlignRight, text)

    def _paint_notice(self, painter: QPainter):
        # Footer: the day the clock is on, so setting it has a visible effect.
        painter.setFont(self._font(16))
        painter.setPen(QColor("#6E86B8"))
        painter.drawText(QRectF(56, 384, 608, 24), Qt.AlignLeft | Qt.AlignVCenter,
                         "BROADCAST DAY: " + self.main.clock.local().strftime("%A %d %B"))

        if not self.notice:
            return
        now = datetime.datetime.now().timestamp()
        if now > self.notice_until:
            self.notice = ""
            return
        painter.setFont(self._font(18))
        painter.setPen(QColor("#8CFF7A"))
        painter.drawText(QRectF(56, 420, 608, 30), Qt.AlignCenter, self.notice)

    # ── input ─────────────────────────────────────────────────────────────

    def handle_input(self, action: str):
        if self.mode == "hotkeys":
            self._handle_hotkeys(action)
            return

        rows = self.rows
        key = rows[self.selected][0]

        if self.editing_clock:
            hh, mm = self._clock_parts()
            if action == "left":
                if self.clock_field == 0:
                    hh = (hh - 1) % 24
                else:
                    mm = (mm - 1) % 60
                self.main.clock.set_wall(hh, mm, 0)
            elif action == "right":
                if self.clock_field == 0:
                    hh = (hh + 1) % 24
                else:
                    mm = (mm + 1) % 60
                self.main.clock.set_wall(hh, mm, 0)
            elif action == "up":
                self.clock_field ^= 1
            elif action in ("enter", "down"):
                self.editing_clock = False
                self._set_notice(f"CLOCK SET TO {self._clock_text()}")
            elif action in ("back", "menu"):
                self.editing_clock = False
            self.update()
            return

        if action == "up":
            self.selected = (self.selected - 1) % len(rows)
            self.update()
        elif action == "down":
            self.selected = (self.selected + 1) % len(rows)
            self.update()
        elif action in ("left", "right"):
            self._change(key, +1 if action == "right" else -1)
        elif action == "enter":
            self._activate(key)
        elif action in ("back", "menu"):
            self.main.close_settings()

    def _change(self, key: str, delta: int):
        s = self.main.settings
        if key == "format":
            s.set("clock_24h", not s.get("clock_24h", True))
        elif key == "ads":
            s.set("ads_enabled", not s.get("ads_enabled", True))
            self.main.invalidate_timelines()
            self._set_notice("COMMERCIALS " + ("ON" if s.get("ads_enabled") else "OFF"))
        elif key == "audio":
            s.set("audio_leveling", not s.get("audio_leveling", True))
            self._set_notice("TAKES EFFECT NEXT LAUNCH")
        elif key == "volume":
            self.main.change_volume(delta * 5)
        elif key == "clock":
            self.editing_clock = True
            self.clock_field = 0
        self.update()

    def _activate(self, key: str):
        if key == "clock":
            self.editing_clock = True
            self.clock_field = 0
        elif key == "format":
            s = self.main.settings
            s.set("clock_24h", not s.get("clock_24h", True))
        elif key == "ads":
            self._change("ads", 1)
        elif key == "audio":
            self._change("audio", 1)
        elif key == "hotkeys":
            self.mode = "hotkeys"
            self.hotkey_idx = 0
        elif key == "about":
            self.main.close_settings()
        self.update()

    # ── hotkey sub-screen ─────────────────────────────────────────────────

    def _handle_hotkeys(self, action: str):
        if self.capturing_key:
            return                      # a raw key press is on its way
        if action == "up":
            self.hotkey_idx = (self.hotkey_idx - 1) % len(HOTKEY_ACTIONS)
        elif action == "down":
            self.hotkey_idx = (self.hotkey_idx + 1) % len(HOTKEY_ACTIONS)
        elif action == "enter":
            self.capturing_key = True
            self.main.input.capture_next_key(self._on_key_captured)
        elif action in ("back", "menu"):
            self.mode = "rows"
        self.update()

    def _on_key_captured(self, key: int):
        self.capturing_key = False
        action = HOTKEY_ACTIONS[self.hotkey_idx][0]
        self.main.input.set_binding(action, key)
        bindings = dict(self.main.settings.get("hotkeys", {}) or {})
        bindings[action] = int(key)
        self.main.settings.set("hotkeys", bindings)
        self._set_notice(f"{action.upper()} = {key_name(key)}")
        self.update()
