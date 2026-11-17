"""
live.py — Live playback screen with new DDR info card + redesigned bottom bar

Per HANDOVER_UI.md §5 Live:
  - Video fills the window
  - Info card (I toggles, DDR ref): 40,28,640,292 r14
      - bg rgba(2,12,2,.9) with phosphor green grid (rgba(92,255,58,.18), 2px every 40px)
      - 4px border #2C2F2C
      - Photo 16,16,190,256 r10, 4px #DDD border, shows the channel's thumb
      - 4 rows at x226, w398, h58, y = 16/82/148/214:
          black fill, 3px #3A3D3A border, radii 6/6/14/6
          label 18px #D8D8D8 left ("NAME//", "CHANNEL//", "LENGTH//", "SCAN//")
          value 30px phosphor right-aligned with glow 0 0 8 rgba(92,255,58,.7)
  - Bottom bar (40,336,640,116): replaces old gold-block bar
      - Cap ellipse (0,0,76,68) 3px #072040, metal gradient, channel # 34px
      - Pill 48,12,(right),44 r22, 3px border, metal gradient
          Progress fill from left: blue gradient #BFE6FF→#3FA9F5→#1B6FC0
          3px #072040 right edge
      - Plate from x36 y50 to bottom: 3px #1C3F8F border (no top), bottom-right r30
          Fill: 4px gold + 4px #38C8FF + #2F64C4
          Title 26px white (pad-left 44, pad-top 12)
          Subline 20px #D6E6FF (uses position_in_break() / ad_break_count())
  - Auto-hide after 4s of inactivity is still a v0.3 TODO from the original handover
"""

from __future__ import annotations

import datetime
import time
from typing import Optional

from PySide6.QtCore import Qt, QRectF, QTimer, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QPen, QLinearGradient, QRadialGradient,
    QPixmap, QPainterPath,
)
from PySide6.QtWidgets import QWidget, QSizePolicy, QVBoxLayout, QHBoxLayout, QLabel, QFrame

from .base import (
    BaseScreen, draw_text, ellipse_rect, paint_glow, load_texture, ui_font,
    NAVY, GOLD, BLUE, INK, PHOSPHOR, TEXT_PRIMARY, TEXT_DIM,
    METAL_PILL_TOP, METAL_PILL_MID, METAL_PILL_BOT, METAL_BORDER,
    PROGRESS_TOP, PROGRESS_MID, PROGRESS_BOT,
    PLATE_GOLD, PLATE_CYAN, PLATE_BLUE, PLATE_BORDER,
    TEXT_SHADOW_COLOR, UI_FONT,
    SAFE_LEFT, SAFE_RIGHT, SAFE_TOP, SAFE_BOTTOM,
)
from ..playlist import PlayItem, position_in_break, ad_break_count
from ..catalog import Channel


# DDR card constants
CARD_BG       = QColor(2, 12, 2, 230)   # ~0.9 alpha
CARD_GRID     = QColor(92, 255, 58, 46)  # ~0.18 alpha
CARD_BORDER   = QColor("#2C2F2C")
CARD_PHOTO_BORDER = QColor("#DDDDDD")
CARD_ROW_BG   = QColor("#000000")
CARD_ROW_BORDER = QColor("#3A3D3A")
CARD_LABEL_COLOR = QColor("#D8D8D8")


class LiveScreen(BaseScreen):
    """Live TV / playback screen."""

    # CRT safe box — measured from the user's red box on the calibration photo
    # (v0.7.2).  Kept as class attributes so the self-test and tools can read the
    # same numbers; the values come from base.py.
    SAFE_LEFT = SAFE_LEFT
    SAFE_RIGHT = SAFE_RIGHT
    SAFE_TOP = SAFE_TOP
    SAFE_BOTTOM = SAFE_BOTTOM
    # v0.6.3: the logo position now comes from the box the user drew on a
    # screenshot, not from the safe-area maths. Measured off that screenshot
    # (672x449 capture of the 720x480 raster) and mapped up:
    #     box left 22 -> 24 px,  box bottom 431 -> 461 px
    # The logo's bottom-left corner sits on the box's bottom-left corner; the
    # logo is ~80 px tall, so it fills the box (which was ~128x88).
    WATERMARK_LEFT = 30          # px from the left edge of the 720x480 raster
    WATERMARK_BOTTOM = 450       # 8 px lower than v0.7.2 (sits on the visible edge)
    WATERMARK_MARGIN = 10        # legacy: only used by the safe-area fallback
    WATERMARK_OPACITY = 0.60     # v0.7.3 (was 0.85)

    # ── Channel number OSD (v0.6.5) ───────────────────────────────────────
    # The green digits a CRT / cable box put in the corner on a channel change.
    # Bedstead at 80 px = 8 font pixels on the 10-row grid, so the digits stay
    # crisp with antialiasing off; drawn inside the measured safe box.
    OSD_PIXEL_SIZE = 80
    OSD_RIGHT = SAFE_RIGHT - 12  # right edge of the digits (in the visible corner)
    OSD_TOP = SAFE_TOP + 12      # top of the digits
    OSD_HOLD_S = 4.0             # how long it stays fully readable
    OSD_COLOR = QColor("#33FF33")
    OSD_OUTLINE = QColor(0, 0, 0, 235)

    #: Snow bursts for this long like a real tuner; if the file still is not
    #: ready the cover turns black instead of snowing on forever.
    SNOW_BURST_S = 1.1

    # ── Channel banner (v0.7.7) ──────────────────────────────────────────
    # The bar a cable box puts at the bottom when you land on a station —
    # replaces the DDR card "I" used to open.  Inside the measured safe box.
    BANNER_X = SAFE_LEFT + 4
    BANNER_W = (SAFE_RIGHT - SAFE_LEFT) - 8
    BANNER_H = 104
    BANNER_BOTTOM = SAFE_BOTTOM - 2
    BANNER_HOLD_S = 6.0

    def __init__(self, main_window, video_widget: QWidget, parent=None):
        super().__init__(main_window, parent)
        self.video_widget = video_widget

        # Video widget — VlcPlayer binds set_hwnd() to this.
        # v0.3.8: video_widget starts at FULL screen (y=0, height=480).
        # In library mode, when the bar is visible, it shrinks to y=60, height=420.
        # In TV mode, it always fills the whole screen (no bar strip at all).
        self.video_widget.setParent(self)
        # v0.5: the video always fills the screen.  The progress bar and every
        # other overlay are painted by VideoOverlay (a separate transparent
        # window above the VLC surface), so nothing has to be resized to make
        # room for them any more — which used to make the picture jump.
        self._bar_strip_height = 60
        self.video_widget.setGeometry(0, 0, self.width(), self.height())

        # ── Channel banner (v0.7.7) ────────────────────────────────────
        self._banner_alpha = 0.0
        self._banner_until = 0.0
        self._banner_data = None
        self._banner_timer = QTimer(self)
        self._banner_timer.setInterval(40)
        self._banner_timer.timeout.connect(self._tick_banner)

        # ── Paused state (v0.3.7) ──────────────────────────────────────────
        self._paused = False

        # ── Bottom bar: real fade in/out (v0.5) ────────────────────────────
        self._bar_visible = True
        self._bar_alpha = 0.0            # painted opacity (0..1)
        self._bar_target_alpha = 1.0
        self._bar_anim_timer = QTimer(self)
        self._bar_anim_timer.setInterval(33)      # ~30fps
        self._bar_anim_timer.timeout.connect(self._tick_bar_anim)

        self._last_input_time = datetime.datetime.now()
        self._autohide_timer = QTimer(self)
        self._autohide_timer.setSingleShot(True)
        self._autohide_timer.setInterval(4000)
        self._autohide_timer.timeout.connect(self._hide_bar)
        self._autohide_timer.start()

        # ── Channel logo watermark (v0.5) ──────────────────────────────────
        # Drawn by the overlay window instead of VLC's logo sub-source, which
        # does not render on this machine at all (see overlay.py).
        self._logo_pixmap: Optional[QPixmap] = None
        self._logo_scaled: Optional[QPixmap] = None
        self._logo_shadow: Optional[QPixmap] = None
        self._watermark_alpha = 1.0          # 1.0 = logo shown, 0.0 = hidden (ad break)
        self._watermark_target_alpha = 1.0
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(33)     # ~30fps for smooth fade
        self._fade_timer.timeout.connect(self._tick_fade)

        # ── Tuning snow (v0.5) ─────────────────────────────────────────────
        # Full-frame 720x480 noise painted by the overlay.  It covers the
        # moment where VLC is still showing frame 0 before the seek lands, and
        # it is 4:3 by construction (the old tv_static.mp4 had black bars baked
        # into the frame, which is what "not cropped" was about).
        self._tuning_alpha = 0.0
        self._tuning_hold = False            # True while the tune is settling
        self._cover_black = False
        self._cover_burst_until = 0.0        # snow turns black after this
        self._black_pixmap: Optional[QPixmap] = None
        self._noise_pixmap = self._make_noise_pixmap(720, 480)
        self._tuning_timer = QTimer(self)
        self._tuning_timer.setInterval(40)   # 25fps snow
        self._tuning_timer.timeout.connect(self._tick_tuning)

        # ── Channel number OSD (v0.6.5) ────────────────────────────────────
        self._osd_text = ""
        self._osd_alpha = 0.0
        self._osd_until = 0.0
        self._osd_timer = QTimer(self)
        self._osd_timer.setInterval(40)      # fade at 25fps
        self._osd_timer.timeout.connect(self._tick_osd)

        # ── Volume OSD (v0.7.0) ────────────────────────────────────────────
        # Same idea, bottom-right: a green bar, so raising the volume during a
        # loud ad break is possible without leaving the picture.
        self._vol_level = 0
        self._vol_alpha = 0.0
        self._vol_until = 0.0
        self._vol_timer = QTimer(self)
        self._vol_timer.setInterval(40)
        self._vol_timer.timeout.connect(self._tick_volume_osd)

        # ── System toast (v0.7.1) ──────────────────────────────────────────
        # A short centred line for things you change while watching (the
        # per-file aspect override).  Same green, no bar.
        self._sys_text = ""
        self._sys_alpha = 0.0
        self._sys_until = 0.0
        self._sys_timer = QTimer(self)
        self._sys_timer.setInterval(40)
        self._sys_timer.timeout.connect(self._tick_system_osd)

        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

    def resizeEvent(self, event):
        # v0.5: the video widget always fills the screen; overlays live in a
        # separate window (VideoOverlay) and are repositioned by it.
        self.video_widget.setGeometry(0, 0, self.width(), self.height())
        self._noise_pixmap = self._make_noise_pixmap(self.width(), self.height())
        super().resizeEvent(event)

    # ── Public update hooks (called by MainWindow) ─────────────────────────

    def on_show(self):
        """Called when LiveScreen becomes active — show the bar and restart
        the auto-hide timer."""
        self._show_bar()
        # A number left over from the last visit must not reappear.  (A tune
        # sets its own OSD *after* show_live(), so this cannot wipe it.)
        self._osd_text = ""
        self._osd_alpha = 0.0
        self._osd_timer.stop()

    def update_now_playing(self, item: PlayItem, channel: Channel, queue_idx: int):
        """Called when the player advances to a new item."""
        self.current_item = item
        self.current_channel = channel
        self.current_idx = queue_idx
        # Library playback has no channel number to show.
        if channel is None or channel.id == "library":
            self._osd_text = ""
            self._osd_alpha = 0.0
            self._osd_timer.stop()
        self.set_channel_logo(channel.logo if channel else None)
        self._show_bar()

        # ── Watermark fade: hide during ad breaks ──────────────────────────
        new_target = 0.0 if item.kind == "ad" else 1.0
        if new_target != self._watermark_target_alpha:
            self._watermark_target_alpha = new_target
            if not self._fade_timer.isActive():
                self._fade_timer.start()

        self._repaint_overlay()

    # ── Tuning snow (v0.5) ────────────────────────────────────────────────

    def _cover_pixmap(self):
        """What covers the picture while tuning / resuming: snow or plain black."""
        if self._cover_black:
            pm = self._black_pixmap
            if pm is None or pm.size() != self.size():
                pm = QPixmap(max(1, self.width()), max(1, self.height()))
                pm.fill(QColor(0, 0, 0))
                self._black_pixmap = pm
            return pm
        return self._make_noise_pixmap(self.width(), self.height())

    def begin_tune(self, black: bool = False):
        """Cover the picture (full-frame snow, or black=True) while a channel is
        tuned or a video resumes after a commercial break. Held at full opacity
        until end_tune(), so the first frame of the video (position 0) can
        never flash on screen.

        v0.6.5: the snow only lasts SNOW_BURST_S (a real tuner burst).  If the
        file is still not seeked by then, the cover turns black and holds — on
        the 1.2 GB MPEG-PS captures the snow used to sit there for seconds,
        which reads as "broken" rather than "changing channel".
        """
        self._cover_black = black
        self._cover_burst_until = 0.0 if black else time.monotonic() + self.SNOW_BURST_S
        self._tuning_hold = True
        self._tuning_alpha = 1.0
        self._noise_pixmap = self._cover_pixmap()
        if not self._tuning_timer.isActive():
            self._tuning_timer.start()
        self._repaint_overlay()

    def end_tune(self):
        """Release the snow; it fades out over ~250 ms."""
        self._tuning_hold = False

    def _tick_tuning(self):
        """While holding: refresh the snow every frame.  After release: fade."""
        if self._tuning_hold:
            if (not self._cover_black and self._cover_burst_until
                    and time.monotonic() >= self._cover_burst_until):
                self._cover_black = True      # tuner burst over, still not ready
            self._noise_pixmap = self._cover_pixmap()
        elif self._tuning_alpha > 0.02:
            self._tuning_alpha *= 0.72          # ~5 frames to fade out
            self._noise_pixmap = self._cover_pixmap()
        else:
            self._tuning_alpha = 0.0
            self._tuning_timer.stop()
        self._repaint_overlay()

    def _tick_fade(self):
        """Animate the logo alpha toward the target value."""
        if abs(self._watermark_alpha - self._watermark_target_alpha) < 0.01:
            self._watermark_alpha = self._watermark_target_alpha
            self._fade_timer.stop()
            self._repaint_overlay()
            return
        delta = self._watermark_target_alpha - self._watermark_alpha
        self._watermark_alpha += delta * 0.20
        self._repaint_overlay()

    # ── Channel number OSD (v0.6.5) ────────────────────────────────────────

    def show_channel_osd(self, number: int):
        """Show the channel number the way a CRT did: green digits in the
        corner on a channel change, held a few seconds, then faded out."""
        try:
            self._osd_text = f"{int(number):02d}"
        except (TypeError, ValueError):
            self._osd_text = str(number)
        self._osd_alpha = 1.0
        self._osd_until = time.monotonic() + self.OSD_HOLD_S
        if not self._osd_timer.isActive():
            self._osd_timer.start()
        self._repaint_overlay()

    def clear_channel_osd(self):
        self._osd_timer.stop()
        self._osd_text = ""
        self._osd_alpha = 0.0
        self._repaint_overlay()

    def _tick_osd(self):
        """Hold at full brightness, then fade over ~5 frames."""
        if self._osd_alpha <= 0.01:
            self._osd_timer.stop()
            return
        if time.monotonic() < self._osd_until:
            return                       # still holding; nothing to repaint
        self._osd_alpha *= 0.72
        if self._osd_alpha <= 0.02:
            self._osd_alpha = 0.0
            self._osd_timer.stop()
        self._repaint_overlay()

    # ── Volume OSD (v0.7.0) ────────────────────────────────────────────────

    def show_volume_osd(self, level: int):
        self._vol_level = max(0, min(100, int(level)))
        self._vol_alpha = 1.0
        self._vol_until = time.monotonic() + 1.6
        if not self._vol_timer.isActive():
            self._vol_timer.start()
        self._repaint_overlay()

    def _tick_volume_osd(self):
        if self._vol_alpha <= 0.01:
            self._vol_timer.stop()
            return
        if time.monotonic() < self._vol_until:
            return
        self._vol_alpha *= 0.72
        if self._vol_alpha <= 0.02:
            self._vol_alpha = 0.0
            self._vol_timer.stop()
        self._repaint_overlay()

    # ── System toast (v0.7.1) ──────────────────────────────────────────────

    def show_system_osd(self, text: str, hold_s: float = 2.2):
        self._sys_text = str(text)
        self._sys_alpha = 1.0
        self._sys_until = time.monotonic() + hold_s
        if not self._sys_timer.isActive():
            self._sys_timer.start()
        self._repaint_overlay()

    def _tick_system_osd(self):
        if self._sys_alpha <= 0.01:
            self._sys_timer.stop()
            return
        if time.monotonic() < self._sys_until:
            return
        self._sys_alpha *= 0.72
        if self._sys_alpha <= 0.02:
            self._sys_alpha = 0.0
            self._sys_timer.stop()
        self._repaint_overlay()

    def _paint_system_osd(self, painter: QPainter):
        if self._sys_alpha <= 0.01 or not self._sys_text:
            return
        font = ui_font(26)
        fm = QFontMetrics(font)
        text = self._sys_text
        tw = fm.horizontalAdvance(text)
        x = (self.width() - tw) // 2
        top = SAFE_BOTTOM - 92

        painter.save()
        painter.setOpacity(self._sys_alpha)
        painter.setFont(font)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, False)
        painter.setPen(QColor(0, 0, 0, 170))
        painter.drawRect(QRectF(x - 12, top - 4, tw + 24, fm.height() + 8))
        painter.setPen(self.OSD_OUTLINE)
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            painter.drawText(x + dx, top + fm.ascent() + dy, text)
        painter.setPen(self.OSD_COLOR)
        painter.drawText(x, top + fm.ascent(), text)
        painter.restore()

    def _paint_volume_osd(self, painter: QPainter):
        """'VOL' + a blocky bar, centred along the bottom edge."""
        if self._vol_alpha <= 0.01:
            return
        font = ui_font(22)
        fm = QFontMetrics(font)
        label = f"VOL {self._vol_level:02d}"
        lw = fm.horizontalAdvance(label)
        bar_w, bar_h = 120, 14
        total = lw + 12 + bar_w
        x = (self.width() - total) // 2
        top = SAFE_BOTTOM - 48

        painter.save()
        painter.setOpacity(self._vol_alpha)
        painter.setFont(font)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, False)
        painter.setPen(self.OSD_OUTLINE)
        painter.drawText(x + 2, top + fm.ascent() + 2, label)
        painter.drawText(x - 2, top + fm.ascent(), label)
        painter.setPen(self.OSD_COLOR)
        painter.drawText(x, top + fm.ascent(), label)

        bx = x + lw + 12
        by = top + 4
        painter.setPen(self.OSD_OUTLINE)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRect(QRectF(bx, by, bar_w, bar_h))
        filled = int(bar_w * self._vol_level / 100.0)
        if filled > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.OSD_COLOR)
            painter.drawRect(QRectF(bx + 2, by + 2, max(0, filled - 4), bar_h - 4))
        painter.restore()

    def _make_noise_pixmap(self, w: int, h: int) -> "QPixmap":
        """One frame of analog snow, generated at 240x160 then blown up with
        nearest-neighbour so it stays chunky on the CRT.

        Adds the two things that make it read as *TV* snow rather than random
        noise: a slow diagonal hum bar and a couple of tearing lines.
        """
        try:
            import numpy as np
            from PySide6.QtGui import QImage
            sw, sh = 240, 160
            arr = np.random.randint(0, 256, (sh, sw), dtype=np.uint8)
            # rolling hum bar
            band = (self._noise_phase if hasattr(self, "_noise_phase") else 0) % sh
            self._noise_phase = band + 6
            rows = np.arange(sh)[:, None]
            dist = np.minimum(np.abs(rows - band), sh - np.abs(rows - band))
            arr = np.clip(arr.astype(np.int16) + (18 - dist * 2).clip(-40, 18), 0, 255).astype(np.uint8)
            # tearing lines
            for _ in range(2):
                y = np.random.randint(0, sh)
                arr[y] = 240
            qimg = QImage(arr.tobytes(), sw, sh, sw, QImage.Format_Grayscale8)
            pm = QPixmap.fromImage(qimg)
            return pm.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        except ImportError:
            pm = QPixmap(w, h)
            pm.fill(QColor("#000000"))
            return pm

    def update_position(self, position_fraction: float, length_ms: int):
        """Called from VlcPlayer's position signal (~4 Hz)."""
        self.current_position = position_fraction
        self.current_length_ms = length_ms
        self.update()

    # ── Auto-hide logic ────────────────────────────────────────────────────

    def _show_bar(self):
        """Fade the bar in (library mode) and restart the auto-hide timer."""
        self._last_input_time = datetime.datetime.now()
        self._bar_visible = True
        self._animate_bar(1.0)
        self._autohide_timer.start()

    def _hide_bar(self):
        """Fade the bar out after 4 s of inactivity (or after a pause/seek)."""
        if self._is_paused():
            self._autohide_timer.start()
            return
        self._bar_visible = False
        self._animate_bar(0.0)

    def _animate_bar(self, target: float):
        """Animate the bar's opacity toward `target` (30 fps, ~8 frames)."""
        self._bar_target_alpha = target
        if abs(self._bar_alpha - target) < 0.01:
            self._bar_alpha = target
            self._repaint_overlay()
            return
        if not self._bar_anim_timer.isActive():
            self._bar_anim_timer.start()

    def _tick_bar_anim(self):
        step = 0.10                      # ~330 ms fade at 30 fps
        if self._bar_alpha < self._bar_target_alpha:
            self._bar_alpha = min(self._bar_target_alpha, self._bar_alpha + step)
        elif self._bar_alpha > self._bar_target_alpha:
            self._bar_alpha = max(self._bar_target_alpha, self._bar_alpha - step)
        if abs(self._bar_alpha - self._bar_target_alpha) < 0.01:
            self._bar_alpha = self._bar_target_alpha
            self._bar_anim_timer.stop()
        self._repaint_overlay()

    # ── Paint ───────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        # Everything that has to appear on top of the picture is drawn by
        # VideoOverlay (a separate always-on-top window) through paint_overlay().
        # This screen only clears its own surface — visible before the first
        # media loads, and wherever the video isn't.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        painter.end()

    # ── Overlay painting (called by VideoOverlay) ──────────────────────────

    def _repaint_overlay(self):
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            overlay.refresh()
        else:
            self.update()

    def paint_overlay(self, painter: QPainter, w: int, h: int):
        """Draw every layer that must appear ON TOP of the video.

        The canvas is exactly the size of the video area, so the coordinates
        below are the familiar 720x480 raster coordinates.
        """
        # 1. bottom progress bar (library mode only — a TV channel has none)
        if self._is_library_mode() and self._bar_alpha > 0.01:
            self._paint_library_progress_bar(painter, w, h, self._bar_alpha)

        # 2. channel banner — number + logo, title, times, next up, blurb
        self._paint_info_banner(painter)

        # 3. channel logo watermark
        if not self._is_library_mode():
            self._paint_channel_logo(painter, w, h)

        # 4. PAUSED
        if self._is_paused():
            self._paint_paused_overlay(painter)

        # 5. tuning snow — above everything, so frame 0 can never show through
        if (self._tuning_alpha > 0.01 and self._noise_pixmap
                and not self._noise_pixmap.isNull()):
            painter.save()
            painter.setOpacity(self._tuning_alpha)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
            painter.drawPixmap(0, 0, w, h, self._noise_pixmap)
            painter.restore()

        # 6. channel number OSD — above the snow, like a real set: the number
        # was on screen while the picture was still rolling.  (The banner also
        # carries the number, but it sits at the bottom and the digits at the
        # top, so they don't collide the way the old card did.)
        self._paint_channel_osd(painter)

        # 7. volume bar (v0.7.0), bottom-centre — above everything.
        self._paint_volume_osd(painter)

        # 8. system toast (aspect / mode changes, v0.7.1), above the volume bar.
        self._paint_system_osd(painter)

    def _paint_channel_osd(self, painter: QPainter):
        """Green pixel digits, top-right corner, 2 px black outline.

        Bedstead at 80 px (8 font pixels) with antialiasing off, so the digits
        stay as crisp as the rest of the UI on the tube.  The outline keeps
        them readable over snow and over a white frame.
        """
        if self._osd_alpha <= 0.01 or not self._osd_text:
            return
        font = ui_font(self.OSD_PIXEL_SIZE)
        fm = QFontMetrics(font)
        text = self._osd_text
        x = self.OSD_RIGHT - fm.horizontalAdvance(text)
        baseline = self.OSD_TOP + fm.ascent()

        painter.save()
        painter.setOpacity(self._osd_alpha)
        painter.setFont(font)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, False)
        painter.setPen(self.OSD_OUTLINE)
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2),
                       (-2, -2), (2, -2), (-2, 2), (2, 2)):
            painter.drawText(x + dx, baseline + dy, text)
        painter.setPen(self.OSD_COLOR)
        painter.drawText(x, baseline, text)
        painter.restore()

    def _is_paused(self) -> bool:
        """True when VLC is paused."""
        return getattr(self, "_paused", False)

    def _paint_paused_overlay(self, painter: QPainter):
        """Plain 'PAUSED' centred on the picture — white text on a dark plate so
        it stays readable on bright frames (and on a CRT, where white on white
        washes out)."""
        w, h = self.width(), self.height()
        if self._bar_visible and self._is_library_mode():
            cy = (self._bar_strip_height + h) // 2
        else:
            cy = h // 2

        font = ui_font(40)
        fm = QFontMetrics(font)
        text = "PAUSED"
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        tx = (w - tw) // 2
        ty = cy + fm.ascent() // 2

        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 165))
        painter.drawRoundedRect(
            QRectF(tx - 18, cy - th // 2 - 8, tw + 36, th + 16), 6, 6)
        painter.setFont(font)
        painter.setPen(QColor(0, 0, 0, 200))
        painter.drawText(tx + 2, ty + 2, text)
        painter.drawText(tx + 3, ty + 2, text)      # bold emulation
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(tx, ty, text)
        painter.drawText(tx + 1, ty, text)          # bold emulation
        painter.restore()

    def _is_library_mode(self) -> bool:
        """True when playing a library item (not a TV channel).
        In library mode: bar always visible + up/down seek instead of
        channel-up/channel-down."""
        ch = getattr(self, "current_channel", None)
        return ch is None or ch.id == "library"

    @staticmethod
    def _fmt_time(seconds: int) -> str:
        """Format seconds as H:MM:SS or M:SS (like TiVo's progress display)."""
        if seconds < 0:
            seconds = 0
        if seconds >= 3600:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            return f"{h}:{m:02d}:{s:02d}"
        m = seconds // 60
        s = seconds % 60
        return f"{m}:{s:02d}"

    # ── Channel logo watermark (v0.5) ──────────────────────────────────────

    def set_channel_logo(self, path):
        """Load the channel's Logos/logo.png (absolute path, or relative to
        the project root).  None / missing file clears it."""
        if getattr(self, "_logo_path", "__unset__") == path:
            return
        self._logo_path = path
        pm = None
        if path:
            from pathlib import Path
            full = Path(path)
            if not full.is_absolute():
                full = Path(__file__).resolve().parent.parent.parent / path
            if full.exists():
                candidate = QPixmap(str(full))
                if not candidate.isNull():
                    pm = candidate
        self._logo_pixmap = pm
        self._logo_scaled = None
        self._logo_shadow = None
        self._repaint_overlay()

    def _scaled_logo(self):
        """Fit the logo into a 160x80 box once, then reuse it (plus its shadow)."""
        if self._logo_pixmap is None:
            return None
        if self._logo_scaled is None:
            self._logo_scaled = self._logo_pixmap.scaled(
                160, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # A black silhouette of the same shape, used as a drop shadow so the
            # watermark stays readable on bright pictures (white/yellow logos
            # disappear on a near-white frame at low opacity).
            shadow = QPixmap(self._logo_scaled.size())
            shadow.fill(Qt.transparent)
            pp = QPainter(shadow)
            pp.drawPixmap(0, 0, self._logo_scaled)
            pp.setCompositionMode(QPainter.CompositionMode_SourceIn)
            pp.fillRect(shadow.rect(), QColor(0, 0, 0, 255))
            pp.end()
            self._logo_shadow = shadow
        return self._logo_scaled

    def watermark_origin(self, logo_h: int) -> tuple[int, int]:
        """Top-left corner of the watermark for a logo `logo_h` px tall.

        Single source of truth: the painter and tools/selftest_ui.py both call
        this, so the verification can never drift from the real position.
        v0.6.3: taken from the box the user drew — bottom-left corner at
        (WATERMARK_LEFT, WATERMARK_BOTTOM).
        """
        return (self.WATERMARK_LEFT, self.WATERMARK_BOTTOM - logo_h)

    def _paint_channel_logo(self, painter: QPainter, w: int, h: int):
        """Channel watermark, inside the CRT's visible box.

        v0.6.1: it used to sit at 10 px from the *screen* edge, which is inside
        the overscan on the Aiwa — the left edge of the logo was cut off. It is
        now placed inside the measured safe area (x 72..652, y 48..431) with a
        10 px margin.

        v0.5.2: 85 % opacity + a 2 px black drop shadow, because at 55 % with no
        shadow the logo vanished over bright pictures.

        VLC's own logo sub-source was tried for this (v0.4.1) and renders
        nothing on this machine — see overlay.py.
        """
        if self._watermark_alpha <= 0.01:
            return
        pm = self._scaled_logo()
        if pm is None:
            return
        x, y = self.watermark_origin(pm.height())
        # the banner takes over the bottom-left corner: fade the logo out while
        # it is up instead of letting the panel cut it in half.
        vis = self._watermark_alpha * (1.0 - self._banner_alpha)
        painter.save()
        if self._logo_shadow is not None:
            painter.setOpacity(0.55 * self.WATERMARK_OPACITY * vis)
            painter.drawPixmap(x + 2, y + 2, self._logo_shadow)
        painter.setOpacity(self.WATERMARK_OPACITY * vis)
        painter.drawPixmap(x, y, pm)
        painter.restore()

    def _paint_library_progress_bar(self, painter: QPainter, w: int, h: int, alpha: float):
        """Bottom progress bar for library playback (fades, never truncates).

        v0.5: painted on the overlay window (so it sits on top of the video),
        opacity is animated by `_animate_bar()`, and the title is elided with
        QFontMetrics.elidedText() into the space the time readout leaves —
        long Japanese titles now end in an ellipsis instead of being cut off
        mid-glyph.
        """
        if not getattr(self, "current_item", None) or alpha <= 0.01:
            return

        bar_h = self._bar_strip_height          # 60 px
        # v0.7.2: sit on the *visible* bottom edge, not the raster's (the tube
        # crops the last ~36 px, which used to eat the bottom third of the bar).
        bar_y = min(h - bar_h, SAFE_BOTTOM - bar_h)

        painter.save()
        painter.setOpacity(alpha)

        # ── panel ─────────────────────────────────────────────────────────
        painter.setPen(QPen(QColor("#1C3F8F"), 3))
        painter.setBrush(QColor(10, 10, 30, 235))
        painter.drawRect(QRectF(0, bar_y, w, bar_h))

        # ── time readout (right) ──────────────────────────────────────────
        length_ms = getattr(self, "current_length_ms", 0) or 0
        # Prefer the length we probed from the file itself: libvlc can still be
        # reporting the previous media's length in the first second after a
        # switch (that is how the bar ended up showing the wrong total).
        video = getattr(self.current_item, "video", None)
        item_len_ms = int((video.duration or 0.0) * 1000) if video else 0
        if item_len_ms > 0:
            length_ms = item_len_ms
        position = getattr(self, "current_position", 0.0) or 0.0
        if length_ms > 0:
            length_s = int(length_ms // 1000)
            cur_s = int(position * length_s)
            time_text = f"{self._fmt_time(cur_s)} / {self._fmt_time(length_s)}"
        else:
            time_text = "0:00 / 0:00"

        text_font = ui_font(18)
        fm = QFontMetrics(text_font)
        time_w = fm.horizontalAdvance(time_text)
        text_y = bar_y + 5
        text_h = 22

        painter.setFont(text_font)
        painter.setPen(QColor(0, 0, 0, 200))
        painter.drawText(QRectF(2, text_y + 2, w - 16, text_h),
                         Qt.AlignVCenter | Qt.AlignRight, time_text)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(0, text_y, w - 16, text_h),
                         Qt.AlignVCenter | Qt.AlignRight, time_text)

        # ── title (left, elided) ──────────────────────────────────────────
        title = "PLAYING: " + (self.current_item.video.title
                               if self.current_item.video else "---")
        avail = max(60, w - 16 - 16 - time_w - 24)
        elided = fm.elidedText(title, Qt.ElideRight, int(avail))

        painter.setPen(QColor(0, 0, 0, 200))
        painter.drawText(QRectF(18, text_y + 2, avail, text_h),
                         Qt.AlignVCenter | Qt.AlignLeft, elided)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(16, text_y, avail, text_h),
                         Qt.AlignVCenter | Qt.AlignLeft, elided)

        # ── progress track ────────────────────────────────────────────────
        track_x = 16
        track_y = bar_y + 32
        track_w = w - 32
        track_h = 16

        painter.setPen(QPen(QColor("#000000"), 2))
        painter.setBrush(QColor("#0A0A1F"))
        painter.drawRoundedRect(QRectF(track_x, track_y, track_w, track_h), 4, 4)

        progress_w = int(track_w * max(0.0, min(1.0, position)))
        if progress_w > 0:
            prog_rect = QRectF(track_x, track_y, progress_w, track_h)
            grad = QLinearGradient(track_x, track_y, track_x, track_y + track_h)
            grad.setColorAt(0.0, QColor("#7FFFFF"))
            grad.setColorAt(0.5, QColor("#00E5FF"))
            grad.setColorAt(1.0, QColor("#0080A0"))
            painter.setPen(Qt.NoPen)
            painter.setBrush(grad)
            painter.drawRoundedRect(prog_rect, 4, 4)

            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.drawLine(int(track_x + progress_w - 1), int(track_y + 2),
                             int(track_x + progress_w - 1), int(track_y + track_h - 2))

        painter.restore()

    # ── Channel banner (v0.7.7) ────────────────────────────────────────────────
    # Replaces the DDR card that "I" used to open.  This is what a cable box puts
    # at the bottom when you land on a station: number + logo, what's on, when it
    # ends, what's next, one line about it.  Laid out inside the measured safe
    # box (base.py SAFE_*) so the tube's overscan can't eat it.

    def show_banner(self, seconds: float = None):
        """Fade the banner in and hold it for `seconds` (default BANNER_HOLD_S).

        The content is resolved ONCE here, not in the paint path: rebuilding a
        channel timeline is not cheap on this machine, and paint runs at 25 fps.
        """
        try:
            self._banner_data = self._build_banner_data()
        except Exception:
            self._banner_data = ("--", "—", "", "", "")
        self._banner_alpha = 1.0
        self._banner_until = time.monotonic() + (
            self.BANNER_HOLD_S if seconds is None else max(0.5, seconds))
        if not self._banner_timer.isActive():
            self._banner_timer.start()
        self._repaint_overlay()

    def hide_banner(self):
        """Start the fade-out now (the timer finishes it)."""
        self._banner_until = 0.0
        if not self._banner_timer.isActive():
            self._banner_timer.start()
        self._repaint_overlay()

    def toggle_banner(self):
        """The I key: show it for a while, or dismiss it immediately."""
        if self._banner_alpha > 0.5:
            self.hide_banner()
        else:
            self.show_banner(10.0)

    def _tick_banner(self):
        """Hold at full brightness, then fade over ~5 frames (same as the OSD)."""
        if self._banner_alpha <= 0.01:
            self._banner_timer.stop()
            return
        if time.monotonic() < self._banner_until:
            return
        self._banner_alpha *= 0.72
        if self._banner_alpha <= 0.02:
            self._banner_alpha = 0.0
            self._banner_timer.stop()
        self._repaint_overlay()

    def _fmt_clock(self, ts: float) -> str:
        """The same clock format the guide uses (24 h or 12 h per settings)."""
        try:
            use24 = bool(self.main.settings.get("clock_24h", True))
            return self.main.clock.format_time(ts, use_24h=use24)
        except Exception:
            t = datetime.datetime.fromtimestamp(ts)
            h = t.hour % 12 or 12
            return f"{h}:{t.minute:02d}{'a' if t.hour < 12 else 'p'}"

    def _banner_blocks(self):
        """(airing programme, next programme) for the channel, from the timeline.

        Programme blocks (not segments) on purpose: during a commercial pod the
        banner still has to name the show you are watching.
        """
        ch = getattr(self, "current_channel", None)
        if not ch or self._is_library_mode():
            return None, None
        try:
            tl = self.main.timeline_for(ch)
            now = self.main.clock.now()
            blocks = tl.programme_blocks(now - 3 * 3600, now + 4 * 3600, limit=60)
        except Exception:
            return None, None
        current = None
        for block in blocks:
            if block.start <= now < block.end:
                current = block
                break
        nxt = None
        ref = current.start if current is not None else now
        for block in blocks:
            if block.start >= ref and block is not current:
                nxt = block
                break
        return current, nxt

    def _banner_lines(self):
        """(number, title, times, next_up, blurb) — cached by show_banner().

        Kept as a thin wrapper so old callers/tests still work; the real work is
        in _build_banner_data() and only runs when the banner appears.
        """
        if getattr(self, "_banner_data", None) is None:
            self._banner_data = self._build_banner_data()
        return self._banner_data

    def _build_banner_data(self):
        """The five strings the bar shows.  Runs once per appearance."""
        item = getattr(self, "current_item", None)
        ch = getattr(self, "current_channel", None)
        video = getattr(item, "video", None)
        current, nxt = self._banner_blocks()

        # the timeline wins when it is available: it also covers ad pods, where
        # current_item is a commercial but the *programme* is what matters
        title_video = current.video if current is not None else video
        title = getattr(title_video, "title", "") or "—"
        blurb = (getattr(title_video, "description", "") or "").strip()
        blurb = blurb.splitlines()[0].strip() if blurb else ""

        if self._is_library_mode():
            dur = (getattr(self, "current_length_ms", 0) or 0) / 1000.0
            pos = (getattr(self, "current_position", 0.0) or 0.0) * dur
            number = "LIB"
            times = (f"{self._fmt_time(int(pos))} / {self._fmt_time(int(dur))}"
                     if dur > 0 else "")
            nxt = ""
        else:
            number = f"{ch.number:02d}" if ch else "--"
            if current is not None:
                times = f"{self._fmt_clock(current.start)} – {self._fmt_clock(current.end)}"
            else:
                dur = (getattr(self, "current_length_ms", 0) or 0) / 1000.0
                if dur > 0:
                    pos = (getattr(self, "current_position", 0.0) or 0.0) * dur
                    now = self.main.clock.now()
                    times = (f"{self._fmt_clock(now - pos)} – "
                             f"{self._fmt_clock(now - pos + dur)}")
                else:
                    times = ""
            nxt = f"NEXT  {nxt.video.title}" if nxt is not None else ""

        return number, title, times, nxt, blurb

    def _paint_info_banner(self, painter: QPainter):
        """The bar itself: logo + number, then title / times / next / blurb."""
        if self._banner_alpha <= 0.01:
            return
        bx, bw, bh = self.BANNER_X, self.BANNER_W, self.BANNER_H
        by = self.BANNER_BOTTOM - bh
        data = getattr(self, "_banner_data", None)
        if not data:
            return
        number, title, times, nxt, blurb = data

        painter.save()
        painter.setOpacity(self._banner_alpha)

        # panel: dark glass with a blue frame and a bright top edge
        painter.setPen(QPen(QColor("#2F64C4"), 2))
        painter.setBrush(QColor(6, 8, 30, 232))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 8, 8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#3FA9F5"))
        painter.drawRect(QRectF(bx + 2, by, bw - 4, 3))

        # left column: channel logo above the number
        logo = self._scaled_logo()
        if logo is not None:
            thumb = logo.scaled(64, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(bx + 12 + (64 - thumb.width()) // 2,
                               by + 10 + (36 - thumb.height()) // 2, thumb)
        # Only font sizes the app already renders elsewhere are used here:
        # creating a Bedstead font engine for a NEW pixel size costs seconds on
        # this machine (measured 6 s for the first banner), and paint runs at
        # 25 fps.  20 / 26 / 28 are all in use on the boot, guide and library
        # screens, so their engines are already warm.
        num_font = ui_font(26)
        painter.setFont(num_font)
        painter.setPen(QColor(GOLD))
        painter.drawText(QRectF(bx + 10, by + 46, 74, 36), Qt.AlignCenter, number)

        # divider
        painter.setPen(QPen(QColor("#1C3F8F"), 2))
        painter.drawLine(bx + 92, by + 10, bx + 92, by + bh - 10)

        # right column: four lines
        tx = bx + 104
        tw = bw - 116

        def line(text, y, size, color, box_h):
            if not text:
                return
            font = ui_font(size)
            fm = QFontMetrics(font)
            painter.setFont(font)
            shown = fm.elidedText(text, Qt.ElideRight, int(tw))
            painter.setPen(QColor(0, 0, 0, 160))
            painter.drawText(QRectF(tx + 2, y + 2, tw, box_h),
                             Qt.AlignVCenter | Qt.AlignLeft, shown)
            painter.setPen(color)
            painter.drawText(QRectF(tx, y, tw, box_h),
                             Qt.AlignVCenter | Qt.AlignLeft, shown)

        line(title, by + 4, 28, QColor("#FFFFFF"), 30)
        line(times, by + 34, 20, QColor(GOLD), 22)
        line(nxt, by + 56, 20, QColor("#9FBFEA"), 20)
        line(blurb, by + 76, 20, QColor("#8FA3C8"), 20)

        painter.restore()

    def _paint_bottom_bar(self, painter: QPainter):
        """TV mode bar — also positioned in the top strip (y=0 to y=60).
        v0.3.6: moved from y=336 (bottom, inside video_widget area where
        VLC covers it) to y=0 (top strip, outside video_widget area).
        Library mode uses a separate _paint_library_progress_bar method."""
        if not getattr(self, "current_channel", None) or not getattr(self, "current_item", None):
            return

        # Library mode: use the dedicated slim top progress bar instead
        if self._is_library_mode():
            self._paint_library_progress_bar(painter)
            return

        w, h = self.width(), self.height()
        # v0.3.6: bar now in the top strip (same as library mode) to avoid
        # VLC's direct rendering covering it. TV mode shows the same layout
        # as library mode but with TV-specific text (channel info + ad break).
        bar_x = 0
        bar_y = 0
        bar_w = w
        bar_h = self._bar_strip_height  # 60px

        # Background panel (dark, mostly opaque)
        panel_rect = QRectF(bar_x, bar_y, bar_w, bar_h)
        painter.setPen(QPen(QColor("#1C3F8F"), 3))
        painter.setBrush(QColor(10, 10, 30, 220))
        painter.drawRect(panel_rect)

        # Channel # + name (left side, 18px)
        title_font = QFont(UI_FONT)
        title_font.setPixelSize(18)
        painter.setFont(title_font)
        ch = self.current_channel
        item = self.current_item
        title_text = f"CH {ch.number:02d}  {ch.name}"
        if item.kind == "ad":
            # Show ad info
            queue = getattr(self.main, "current_queue", [])
            idx = getattr(self, "current_idx", 0)
            try:
                from ..playlist import position_in_break, ad_break_count
                pos, tot = position_in_break(queue, idx)
                title_text += f"  -  AD BREAK {pos}/{tot}"
            except Exception:
                pass
        # Shadow
        painter.setPen(QColor(0, 0, 0, 200))
        painter.drawText(QRectF(bar_x + 16 + 2, bar_y + 4 + 2, bar_w // 2, 22),
                          Qt.AlignVCenter | Qt.AlignLeft, title_text)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(bar_x + 16, bar_y + 4, bar_w // 2, 22),
                          Qt.AlignVCenter | Qt.AlignLeft, title_text)

        # Time + title (right side, 18px)
        length_ms = getattr(self, "current_length_ms", 0) or 0
        position = getattr(self, "current_position", 0.0) or 0.0
        if length_ms > 0:
            length_s = int(length_ms // 1000)
            cur_s = int(position * length_s)
            time_text = f"{self._fmt_time(cur_s)} / {self._fmt_time(length_s)}"
        else:
            time_text = "0:00 / 0:00"
        time_font = QFont(UI_FONT)
        time_font.setPixelSize(18)
        painter.setFont(time_font)
        # Shadow
        painter.setPen(QColor(0, 0, 0, 200))
        painter.drawText(QRectF(bar_x + bar_w // 2 + 2, bar_y + 4 + 2,
                                 bar_w // 2 - 16, 22),
                          Qt.AlignVCenter | Qt.AlignRight, time_text)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(bar_x + bar_w // 2, bar_y + 4,
                                 bar_w // 2 - 16, 22),
                          Qt.AlignVCenter | Qt.AlignRight, time_text)

        # Progress bar — slim, prominent, bright blue (TV mode uses blue,
        # library mode uses cyan — slight visual distinction)
        track_x = bar_x + 16
        track_y = bar_y + 30
        track_w = bar_w - 32
        track_h = 18

        # Track background (dark)
        track_rect = QRectF(track_x, track_y, track_w, track_h)
        painter.setPen(QPen(QColor("#000000"), 2))
        painter.setBrush(QColor("#0A0A1F"))
        painter.drawRoundedRect(track_rect, 4, 4)

        # Progress fill (blue gradient for TV mode)
        progress_w = int(track_w * position) if position > 0 else 0
        if progress_w > 0:
            prog_rect = QRectF(track_x, track_y, progress_w, track_h)
            prog_grad = QLinearGradient(track_x, track_y, track_x, track_y + track_h)
            prog_grad.setColorAt(0.0, QColor("#BFE6FF"))   # light blue top
            prog_grad.setColorAt(0.5, QColor("#3FA9F5"))   # blue mid
            prog_grad.setColorAt(1.0, QColor("#1B6FC0"))   # dark blue bot
            painter.setPen(Qt.NoPen)
            painter.setBrush(prog_grad)
            painter.drawRoundedRect(prog_rect, 4, 4)

            # Position marker
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.drawLine(int(track_x + progress_w - 1), int(track_y + 2),
                              int(track_x + progress_w - 1), int(track_y + track_h - 2))

    # ── Input ─────────────────────────────────────────────────────────────

    def handle_input(self, action: str):
        # Any input resets the auto-hide timer
        self._show_bar()

        # ── Library mode (no current channel) ─────────────────────────────
        # Up/down = seek back/forward 10s; left/right = seek back/forward 30s
        # This is the TiVo-style playback control the user wants for library.
        if self._is_library_mode():
            if action == "up":
                self._seek_relative(-10.0)   # back 10s
            elif action == "down":
                self._seek_relative(10.0)    # forward 10s
            elif action == "left":
                self._seek_relative(-30.0)
            elif action == "right":
                self._seek_relative(30.0)
            elif action == "play_pause":
                self._toggle_pause()
            elif action == "back":
                if self._banner_alpha > 0.5:
                    self.hide_banner()
                else:
                    self.main.show_boot()
            elif action == "info":
                self.toggle_banner()
            elif action == "guide":
                self.main.show_guide()
            elif action == "vault":
                self.main.enter_browser_mode()
            elif action == "menu":
                self.main.show_menu()
            return

        # ── TV mode (channel is set) ──────────────────────────────────────
        if action == "up":
            self.main.channel_up()
        elif action == "down":
            self.main.channel_down()
        elif action == "play_pause":
            self._toggle_pause()
        elif action == "back":
            if self._banner_alpha > 0.5:
                self.hide_banner()
            else:
                self.main.show_boot()
        elif action == "info":
            self.toggle_banner()
        elif action == "guide":
            self.main.show_guide()
        elif action == "picker":
            self.main.show_picker()
        elif action == "menu":
            self.main.show_menu()
        elif action == "vault":
            self.main.enter_browser_mode()

    def _toggle_pause(self):
        """Toggle pause state.  The PAUSED text is drawn by the overlay window
        (VideoOverlay); VLC's marquee is no longer used for it."""
        # Don't allow pausing during tuning transition (snow is up)
        if getattr(self.main, '_pending_tune', None) or self._tuning_hold:
            return
        self._paused = not self._paused
        if self._paused:
            if self.main.player:
                self.main.player.pause()
            self._autohide_timer.stop()
        else:
            if self.main.player:
                self.main.player.resume()
            # v0.7.0: the broadcast kept running while we were paused; coming
            # back far behind live rejoins the timeline instead of drifting.
            if hasattr(self.main, "on_resume_from_pause"):
                self.main.on_resume_from_pause()
            self._autohide_timer.start()
        self._show_bar()
        self._repaint_overlay()

    def _seek_relative(self, delta_seconds: float):
        """Seek relative to current position (delta_seconds can be +/-).
        Uses VlcPlayer's current_position + current_length_ms to compute
        the new absolute fraction, then seeks."""
        if not self.main.player:
            return
        length_ms = self.main.player.current_length_ms()
        if length_ms <= 0:
            return  # media not loaded yet
        pos_fraction = self.main.player.current_position()
        cur_seconds = pos_fraction * (length_ms / 1000.0)
        new_seconds = max(0.0, min(cur_seconds + delta_seconds, length_ms / 1000.0))
        new_fraction = new_seconds / (length_ms / 1000.0)
        self.main.player.seek_to(new_fraction)
