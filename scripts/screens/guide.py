"""
guide.py — DirecTV-style grid guide, now a real broadcast guide (v0.7.0)

What changed and why
--------------------
v0.6 and earlier did not read the schedule at all: `mock_schedule_for_channel`
invented four slots labelled 9:30a / 10:00a / 10:30a / 11:00a and filled them
with the channel's videos, so the guide could name a programme that was not on
(“it shows another media filename sometimes”) and the times were decoration.

Now every cell comes from `timeline.py` — the same data the player tunes from —
so the grid is the broadcast: real start/end times, real titles, and the ad
pods are inside the programme slots (the guide lists programmes only, as the
user asked; the player may still land in a pod if you tune in during one).

Time travel
-----------
LEFT / RIGHT slide the window through the next 72 hours, half an hour at a time
— the 24–72 h horizon of an early cable box, not weeks of listings.  The day
column says Today / Tomorrow / a weekday, and a red NOW line marks the present
when it is on screen.

  - Bg = guide_bg.png
  - Info plate 40,24,430,116: title, "NN CHANNEL  start-end", kind
  - Live preview 520,24,160,110 (black until the preview player has a picture)
  - Grid: time header y150 h36, rows y = 194 + r·54, channel cell w104
  - Focus = gold, hint bar at the bottom
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QPen, QLinearGradient, QPixmap,
    QPainterPath,
)
from PySide6.QtWidgets import QWidget

from .base import (
    BaseScreen, paint_glow, load_texture,
    GOLD, GUIDE_ROW_FILL, GUIDE_ROW_DIVIDER, GUIDE_ROW_BOTTOM,
    GUIDE_CHAN_FILL, GUIDE_CHAN_BOTTOM, GUIDE_FRAME_BLUE,
    UI_FONT, SAFE_BOTTOM,
)
from ..catalog import Channel
from ..preview import ChannelPreview

#: Grid geometry (720x480 raster).
TIME_Y = 150
TIME_H = 36
CHAN_COL_W = 104
ROW_H = 50
ROW_GAP = 4
GRID_LEFT = 40
SLOTS = 4
SLOT_S = 30 * 60                 # one column = 30 minutes of broadcast


class GuideScreen(BaseScreen):
    """Broadcast guide: 2-hour window, 72 hours of scrolling."""

    # Preview panel (top-right)
    PREVIEW_X, PREVIEW_Y = 520, 24
    PREVIEW_W, PREVIEW_H = 160, 110
    PREVIEW_CAPTION_TOP = 80

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)
        self.selected_channel_idx: int = 0
        self.current_channel_idx: int = 0
        self._window_start: float = 0.0      # epoch of the left edge
        self._focus_time: float = 0.0        # the highlighted cell (EPG cursor)
        self._now_at_open: float = 0.0

        self._preview_ok = False
        self._preview_ready = False
        self._preview_seq = 0
        self._logo_cache: dict = {}
        self._blocks_cache: dict = {}
        self._blocks_cache_key = None

        self.preview_widget = QWidget(self)
        self.preview_widget.setAttribute(Qt.WA_NativeWindow, True)
        self.preview_widget.setStyleSheet("background:#000000;")
        self.preview_widget.setGeometry(self.PREVIEW_X + 3, self.PREVIEW_Y + 3,
                                        self.PREVIEW_W - 6, self.PREVIEW_CAPTION_TOP)
        self.preview_widget.setVisible(False)
        self._preview = ChannelPreview(self.preview_widget)

        # Poll the preview until it has a real picture (never show frame 0).
        self._preview_poll = QTimer(self)
        self._preview_poll.setInterval(120)
        self._preview_poll.timeout.connect(self._check_preview_ready)

        self.setAttribute(Qt.WA_OpaquePaintEvent)

    # ── clock / window ────────────────────────────────────────────────────

    def now(self) -> float:
        return self.main.clock.now()

    def _round_window(self, t: float) -> float:
        """Snap to the containing half hour."""
        return t - (t % SLOT_S)

    def on_show(self):
        if self.main.current_channel:
            self.current_channel_idx = next(
                (i for i, ch in enumerate(self.main.catalog.channels)
                 if ch.id == self.main.current_channel.id), 0)
            self.selected_channel_idx = self.current_channel_idx
        self._now_at_open = self.now()
        self._window_start = self._round_window(self._now_at_open)
        self._focus_time = self._now_at_open
        self._refresh_preview()
        self.update()

    def hideEvent(self, event):
        self._preview.stop()
        self.preview_widget.setVisible(False)
        self._preview_poll.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if (getattr(self.main, "catalog", None) and self.main.catalog.channels
                and self.isVisible()):
            QTimer.singleShot(0, self._refresh_preview)

    # ── timeline access ───────────────────────────────────────────────────

    def _timeline(self, ch: Channel):
        return self.main.timeline_for(ch)

    def _blocks(self, ch: Channel, t0: float, t1: float):
        key = (ch.id, round(t0), round(t1))
        if self._blocks_cache_key != key:
            self._blocks_cache = {}
            self._blocks_cache_key = key
        if ch.id not in self._blocks_cache:
            try:
                self._blocks_cache[ch.id] = self._timeline(ch).programme_blocks(t0, t1, limit=40)
            except Exception:
                self._blocks_cache[ch.id] = []
        return self._blocks_cache[ch.id]

    def _block_at(self, ch: Channel, t: float):
        """The programme block containing `t` (cheap: one block)."""
        try:
            blocks = self._timeline(ch).programme_blocks(t, t + 1, limit=4)
        except Exception:
            return None
        return blocks[0] if blocks else None

    def _focus_block(self, ch: Channel):
        return self._block_at(ch, self._focus_time)

    # ── preview plumbing ──────────────────────────────────────────────────

    def _channel_logo(self, ch) -> Optional[QPixmap]:
        key = ch.logo or ""
        if key in self._logo_cache:
            return self._logo_cache[key]
        pm = None
        if key:
            from pathlib import Path
            full = Path(key)
            if not full.is_absolute():
                full = Path(__file__).resolve().parent.parent.parent / key
            if full.exists():
                candidate = QPixmap(str(full))
                if not candidate.isNull():
                    pm = candidate
        self._logo_cache[key] = pm
        return pm

    def _preview_target(self, ch):
        """(src, seconds-into-file, length) for what this channel airs now."""
        try:
            air = self._timeline(ch).airing_at(self.now())
        except Exception:
            air = None
        if air is None:
            return None
        try:
            dur = self.main._schedule_state.known_duration(ch.id, air.video.id)
        except Exception:
            dur = 0.0
        dur = dur or float(getattr(air.video, "duration", 0.0) or 0.0)
        return (air.video.src, air.position_at(self.now()), dur)

    def _refresh_preview(self):
        channels = self.main.catalog.channels
        if not channels:
            self._preview_ok = False
            self.preview_widget.setVisible(False)
            return
        ch = channels[max(0, min(self.selected_channel_idx, len(channels) - 1))]
        target = self._preview_target(ch)
        if not target:
            self._preview_ok = False
            self._preview_ready = False
            self.preview_widget.setVisible(False)
            self._preview_poll.stop()
            self.update()
            return
        src, pos, dur = target
        # Hide the native video until the preview player is really showing the
        # join position: a stale frame (or frame 0 of a 1.2 GB MPEG-PS) used to
        # sit there for a second — the same flash as the live screen had.
        self._preview_seq += 1
        self._preview_ready = False
        self._preview_ok = self._preview.play(src, pos, dur)
        self.preview_widget.setVisible(False)
        if self._preview_ok:
            self._preview_poll.start()
        else:
            self._preview_poll.stop()
        self.update()

    def _check_preview_ready(self):
        if not self._preview_ok:
            self._preview_poll.stop()
            return
        ready = self._preview.is_ready()
        if ready:
            self._preview_poll.stop()
            self._preview_ready = True
            self.preview_widget.setVisible(True)
        self.update()

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            w, h = self.width(), self.height()

            tex = load_texture("guide_bg.png")
            if tex is not None and not tex.isNull():
                painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                painter.drawPixmap(0, 0, tex)
            else:
                painter.fillRect(self.rect(), QColor("#0A0A1A"))

            channels = self.main.catalog.channels
            if not channels:
                painter.setFont(self._font(20))
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(self.rect(), Qt.AlignCenter, "No channels available")
                return

            sel_ch = channels[max(0, min(self.selected_channel_idx, len(channels) - 1))]
            self._paint_info_plate(painter, sel_ch)
            self._paint_preview(painter, sel_ch)
            self._paint_header(painter, w)
            self._paint_rows(painter, channels, w, h)
            self._paint_hints(painter, w)
        finally:
            painter.end()

    def _font(self, px: int) -> QFont:
        f = QFont(UI_FONT)
        f.setPixelSize(px)
        return f

    def _time_label(self, ts: float, with_day: bool = False) -> str:
        text = self.main.clock.format_time(ts, use_24h=bool(
            self.main.settings.get("clock_24h", True)))
        if with_day:
            text = f"{self.main.clock.format_day(ts)}  {text}"
        return text

    def _paint_info_plate(self, painter: QPainter, ch: Channel):
        x, y, w, h = 40, 24, 430, 116
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(2, 3, 28, 205))
        painter.drawRect(QRectF(x, y, w, h))
        painter.setPen(QPen(QColor(GUIDE_FRAME_BLUE), 3))
        painter.drawLine(x, y, x + w, y)
        painter.drawLine(x, y + h, x + w, y + h)

        block = self._focus_block(ch)
        title = block.video.title if block else "—"
        title_font = self._font(30)
        painter.setFont(title_font)
        title = QFontMetrics(title_font).elidedText(title, Qt.ElideRight, w - 28)
        painter.setPen(QColor(0, 0, 0, 140))
        painter.drawText(QRectF(x + 16, y + 8, w - 28, 36),
                         Qt.AlignVCenter | Qt.AlignLeft, title)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(x + 14, y + 6, w - 28, 36),
                         Qt.AlignVCenter | Qt.AlignLeft, title)

        when = ""
        if block:
            when = f"{self._time_label(block.start)} - {self._time_label(block.end)}"
        sub = f"{ch.number:02d} {ch.name}   {when}"
        painter.setFont(self._font(20))
        painter.setPen(QColor(0, 0, 0, 140))
        painter.drawText(QRectF(x + 16, y + 44, w - 28, 28),
                         Qt.AlignVCenter | Qt.AlignLeft, sub)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(x + 14, y + 42, w - 28, 28),
                         Qt.AlignVCenter | Qt.AlignLeft, sub)

        now_air = self._timeline(ch).airing_at(self.now())
        state = "ON AIR" if now_air and not now_air.is_ad else (
            "AD BREAK" if now_air else "OFF AIR")
        third = f"{self.main.clock.format_day(self._window_start)}   {state}"
        painter.setPen(QColor(0, 0, 0, 140))
        painter.drawText(QRectF(x + 16, y + 72, w - 28, 28),
                         Qt.AlignVCenter | Qt.AlignLeft, third)
        painter.setPen(QColor("#9FC7FF"))
        painter.drawText(QRectF(x + 14, y + 70, w - 28, 28),
                         Qt.AlignVCenter | Qt.AlignLeft, third)

    def _paint_preview(self, painter: QPainter, ch: Channel):
        x, y, w, h = self.PREVIEW_X, self.PREVIEW_Y, self.PREVIEW_W, self.PREVIEW_H
        video_rect = QRectF(x + 3, y + 3, w - 6, self.PREVIEW_CAPTION_TOP)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#000000"))
        painter.drawRect(video_rect)

        if self._preview_ok and not self._preview_ready:
            painter.setFont(self._font(16))
            painter.setPen(QColor("#5CFF3A"))
            painter.drawText(video_rect, Qt.AlignCenter, "TUNING")
        elif not self._preview_ok:
            painter.setFont(self._font(40))
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(video_rect, Qt.AlignCenter, f"{ch.number:02d}")

        cap_rect = QRectF(x + 3, y + 3 + self.PREVIEW_CAPTION_TOP,
                          w - 6, h - 6 - self.PREVIEW_CAPTION_TOP)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#0A0A20"))
        painter.drawRect(cap_rect)
        painter.setBrush(QColor("#E50000"))
        painter.drawEllipse(QRectF(x + 9, cap_rect.y() + (cap_rect.height() - 8) / 2, 8, 8))

        painter.setFont(self._font(16))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(x + 22, cap_rect.y(), w - 26, cap_rect.height()),
                         Qt.AlignVCenter | Qt.AlignLeft,
                         f"LIVE  {ch.number:02d} {ch.abbrev}")
        painter.setPen(QPen(QColor(GUIDE_FRAME_BLUE), 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(x, y, w, h))

    def _paint_header(self, painter: QPainter, w: int):
        grid_x = GRID_LEFT + CHAN_COL_W
        grid_w = w - GRID_LEFT - grid_x
        # Day label lives in the channel column of the header row (the info
        # plate above ends at y=140, so nothing overlaps it any more).
        painter.setFont(self._font(16))
        painter.setPen(QColor(0, 0, 0, 140))
        painter.drawText(QRectF(GRID_LEFT + 2, TIME_Y + 2, CHAN_COL_W, TIME_H),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         self.main.clock.format_day(self._window_start))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(GRID_LEFT, TIME_Y, CHAN_COL_W, TIME_H),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         self.main.clock.format_day(self._window_start))

        for i in range(SLOTS):
            t = self._window_start + i * SLOT_S
            tx = grid_x + i * (grid_w / SLOTS)
            painter.setFont(self._font(20))
            painter.setPen(QColor(0, 0, 0, 140))
            painter.drawText(QRectF(tx + 8, TIME_Y + 2, grid_w / SLOTS - 12, TIME_H),
                             Qt.AlignVCenter | Qt.AlignLeft, self._time_label(t))
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(QRectF(tx + 6, TIME_Y, grid_w / SLOTS - 12, TIME_H),
                             Qt.AlignVCenter | Qt.AlignLeft, self._time_label(t))

        # vertical hour separators
        painter.setPen(QPen(QColor(74, 125, 224, 70), 2))
        for i in range(SLOTS + 1):
            tx = int(grid_x + i * (grid_w / SLOTS))
            painter.drawLine(tx, TIME_Y + TIME_H - 2, tx, SAFE_BOTTOM - 4)

        # NOW marker
        now = self.now()
        win_end = self._window_start + SLOTS * SLOT_S
        if self._window_start <= now <= win_end:
            nx = int(grid_x + (now - self._window_start) / (SLOTS * SLOT_S) * grid_w)
            painter.setPen(QPen(QColor("#FF4040"), 3))
            painter.drawLine(nx, TIME_Y + TIME_H - 2, nx, SAFE_BOTTOM - 4)

    def _paint_rows(self, painter: QPainter, channels, w: int, h: int):
        grid_x = GRID_LEFT + CHAN_COL_W
        grid_w = w - GRID_LEFT - grid_x
        window_end = self._window_start + SLOTS * SLOT_S

        rows_visible = max(4, (SAFE_BOTTOM - TIME_Y - TIME_H - 40) // (ROW_H + ROW_GAP))
        scroll_offset = max(0, self.selected_channel_idx - rows_visible // 2)
        scroll_offset = min(scroll_offset, max(0, len(channels) - rows_visible))

        for vis_i in range(rows_visible):
            ch_i = scroll_offset + vis_i
            if ch_i >= len(channels):
                break
            ch = channels[ch_i]
            y = TIME_Y + TIME_H + vis_i * (ROW_H + ROW_GAP)
            is_sel = (ch_i == self.selected_channel_idx)

            # channel cell
            chan_grad = QLinearGradient(GRID_LEFT, y, GRID_LEFT, y + ROW_H)
            chan_grad.setColorAt(0.0, QColor(GUIDE_CHAN_FILL))
            chan_grad.setColorAt(1.0, QColor(GUIDE_CHAN_BOTTOM))
            painter.setPen(Qt.NoPen)
            painter.setBrush(chan_grad)
            path = QPainterPath()
            path.moveTo(GRID_LEFT + 6, y)
            path.lineTo(GRID_LEFT + CHAN_COL_W, y)
            path.lineTo(GRID_LEFT + CHAN_COL_W, y + ROW_H)
            path.lineTo(GRID_LEFT + 6, y + ROW_H)
            path.arcTo(QRectF(GRID_LEFT, y + ROW_H - 12, 12, 12), 270, 90)
            path.arcTo(QRectF(GRID_LEFT, y, 12, 12), 180, 90)
            path.closeSubpath()
            painter.drawPath(path)

            logo = self._channel_logo(ch)
            if logo is not None:
                # v0.7.4: logo only, no channel number (the OSD shows the number
                # when flicking) and no gold ring — the programme cell is the
                # selection.
                target_h = 30
                scale = target_h / logo.height()
                scaled_w = max(1, int(logo.width() * scale))
                painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                painter.drawPixmap(int(GRID_LEFT + (CHAN_COL_W - scaled_w) // 2),
                                   int(y + (ROW_H - target_h) // 2),
                                   scaled_w, target_h, logo)
            else:
                painter.setFont(self._font(26))
                painter.setPen(QColor(0, 0, 0, 140))
                painter.drawText(QRectF(GRID_LEFT + 2, y + 4, CHAN_COL_W, 26),
                                 Qt.AlignCenter, f"{ch.number:02d}")
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(QRectF(GRID_LEFT, y + 2, CHAN_COL_W, 26),
                                 Qt.AlignCenter, f"{ch.number:02d}")
                painter.setFont(self._font(20))
                painter.setPen(QColor(0, 0, 0, 140))
                painter.drawText(QRectF(GRID_LEFT + 2, y + 29, CHAN_COL_W, 20),
                                 Qt.AlignCenter, ch.abbrev)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(QRectF(GRID_LEFT, y + 27, CHAN_COL_W, 20),
                                 Qt.AlignCenter, ch.abbrev)

            # programme cells: stretched across the row.
            # v0.7.4: every cell gets at least 96 px (the old slot look), the
            # widths still follow the real durations, and the row always fills
            # the grid — short 10-minute items are no longer 40 px slivers.
            blocks = [b for b in self._blocks(ch, self._window_start, window_end)
                      if b.end > self._window_start and b.start < window_end]
            if blocks:
                spans = [(max(b.start, self._window_start),
                          min(b.end, window_end)) for b in blocks]
                widths = self._stretch_widths([e - s for s, e in spans], grid_w, 96.0)
                x = grid_x
                for b, cw in zip(blocks, widths):
                    focus = is_sel and (b.start <= self._focus_time < b.end)
                    self._paint_cell(painter, b, x, x + cw, y, focus)
                    x += cw

    @staticmethod
    def _stretch_widths(durations, total: float, min_w: float) -> list[float]:
        """Widths that sum to `total`, proportional to the durations but at
        least `min_w` each (when there is room)."""
        n = len(durations)
        if n == 0:
            return []
        if min_w * n >= total:
            return [total / n] * n
        span = sum(durations) or 1.0
        free = total - min_w * n
        return [min_w + free * d / span for d in durations]

    def _paint_cell(self, painter: QPainter, block, x0: float, x1: float,
                    y: float, is_focus: bool):
        cell_w = max(2.0, x1 - x0)
        rect = QRectF(x0 + 1, y, max(2.0, cell_w - 2), ROW_H)

        if is_focus:
            paint_glow(painter, int(x0 - 6), int(y - 6), int(cell_w + 12),
                       int(ROW_H + 12), QColor(255, 176, 0, 180), radius=10)
            painter.setPen(QPen(QColor("#FFE08A"), 3))
            painter.setBrush(QColor(GOLD))
            text_color = QColor("#14143C")
        else:
            painter.setBrush(QColor(GUIDE_ROW_FILL))
            painter.setPen(QPen(QColor(GUIDE_ROW_DIVIDER), 3))
            text_color = QColor("#FFFFFF")

        # One rounded box per cell, inset 1 px.  The old "radius 0 6 6 0" path
        # left a notch where two contiguous cells met; the timeline makes cells
        # contiguous almost everywhere, so a clean box reads better.
        painter.drawRoundedRect(rect, 5, 5)

        font = self._font(20)
        painter.setFont(font)
        fm = QFontMetrics(font)
        text_x = max(x0, 40 + CHAN_COL_W) + 6
        avail = max(20, int(x1 - text_x - 8))
        # v0.7.4: two lines with ellipsis, like a real EPG (and like the Comcast
        # example): a 30-minute cell rarely fits a full title on one line.
        lines = self._title_lines(block.video.title, fm, avail, max_lines=2)
        line_h = 24
        block_h = line_h * len(lines)
        top = y + (ROW_H - block_h) // 2
        for i, line in enumerate(lines):
            ly = top + i * line_h
            painter.setPen(QColor(0, 0, 0, 140))
            painter.drawText(QRectF(text_x + 2, ly + 2, avail, line_h),
                             Qt.AlignVCenter | Qt.AlignLeft, line)
            painter.setPen(text_color)
            painter.drawText(QRectF(text_x, ly, avail, line_h),
                             Qt.AlignVCenter | Qt.AlignLeft, line)

    @staticmethod
    def _title_lines(text: str, fm: QFontMetrics, width: int, max_lines: int = 2):
        """Greedy word wrap; the last line is elided when text is left over."""
        words = str(text).split()
        if not words:
            return [""]
        lines: list[str] = []
        cur = ""
        for i, word in enumerate(words):
            trial = (cur + " " + word) if cur else word
            if fm.horizontalAdvance(trial) <= width or not cur:
                cur = trial
                continue
            lines.append(cur)
            cur = word
            if len(lines) == max_lines:
                break
        if len(lines) < max_lines and cur:
            lines.append(cur)
        # Did we run out of room?
        used = len(" ".join(lines).split())
        if used < len(words) and lines:
            lines[-1] = fm.elidedText(lines[-1] + " " + " ".join(words[used:]),
                                      Qt.ElideRight, width)
        elif lines and fm.horizontalAdvance(lines[-1]) > width:
            lines[-1] = fm.elidedText(lines[-1], Qt.ElideRight, width)
        return lines

    def _paint_hints(self, painter: QPainter, w: int):
        rect = QRectF(40, SAFE_BOTTOM - 30, w - 80, 28)
        painter.setPen(QPen(QColor("#FF8080"), 3))
        painter.setBrush(QColor("#A30000"))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setFont(self._font(18))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(rect, Qt.AlignCenter,
                         "◀ ▶ FUTURE   ENTER WATCH   BACK TV")

    # ── input ─────────────────────────────────────────────────────────────

    def handle_input(self, action: str):
        catalog = self.main.catalog
        if not catalog.channels:
            return

        if action == "up":
            self.selected_channel_idx = (self.selected_channel_idx - 1) % len(catalog.channels)
            self._refresh_preview()
            self.update()
        elif action == "down":
            self.selected_channel_idx = (self.selected_channel_idx + 1) % len(catalog.channels)
            self._refresh_preview()
            self.update()
        elif action == "right":
            self._move_focus(+1)
        elif action == "left":
            self._move_focus(-1)
        elif action == "enter":
            ch = catalog.channels[self.selected_channel_idx]
            self.main.tune_to_channel(ch.number)
            self.main.show_live()
        elif action == "back":
            self.main.show_live()
        elif action == "menu":
            self.main.close_menu()

    def _move_focus(self, direction: int):
        """Move the EPG cursor to the next/previous programme of this channel.

        The window follows so the focused cell stays fully visible — the same
        behaviour as a real guide (and what the info plate describes).
        """
        ch = self.main.catalog.channels[self.selected_channel_idx]
        try:
            blocks = self._timeline(ch).programme_blocks(
                self._focus_time - 6 * 3600, self._focus_time + 12 * 3600, limit=300)
        except Exception:
            return
        idx = next((i for i, b in enumerate(blocks)
                    if b.start <= self._focus_time < b.end), None)
        if idx is None:
            self._focus_time = self.now()
            return
        nidx = max(0, min(len(blocks) - 1, idx + direction))
        if nidx == idx:
            return
        self._focus_time = blocks[nidx].start + 1
        self._ensure_focus_visible()
        self.update()

    def _ensure_focus_visible(self):
        span = SLOTS * SLOT_S
        now = self.now()
        if not (self._window_start <= self._focus_time < self._window_start + span):
            # Page so the focused cell lands one column from the left edge.
            self._window_start = self._round_window(self._focus_time) - SLOT_S
        earliest = self._round_window(now) - 6 * 3600   # can look back a few hours
        latest = self._round_window(now) + self.main.GUIDE_HORIZON_S
        self._window_start = min(max(self._window_start, earliest), latest)
        # v0.7.5: the window cannot always follow the cursor (it stops at the
        # present / the 72 h horizon).  Without these clamps the cursor walked
        # out of the drawn grid — which looked exactly like “the orange highlight
        # disappeared” when pressing LEFT at the live edge.
        if self._focus_time < self._window_start:
            self._focus_time = self._window_start + 1
        elif self._focus_time >= self._window_start + span:
            self._focus_time = self._window_start + span - 1
        self._blocks_cache_key = None

    def _scroll(self, delta_s: float):
        now = self.now()
        # The window never goes backwards past the present, and never further
        # than 72 hours ahead (an early cable box held a day or three).
        earliest = self._round_window(now) - 30 * 60
        latest = self._round_window(now) + self.main.GUIDE_HORIZON_S
        target = min(max(self._window_start + delta_s, earliest), latest)
        if target != self._window_start:
            self._window_start = target
            self._blocks_cache_key = None
            self.update()
