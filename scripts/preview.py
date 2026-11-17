"""
preview.py — a tiny muted libvlc player for the guide's live preview panel

The guide used to show the channel's logo in its top-right panel.  A logo says
nothing about what is on *right now*, so the panel shows the channel itself,
joined at the position it would be at on the wall clock.

This is a second, separate MediaPlayer rendered into its own child widget
(the same `set_hwnd()` trick the main player uses, which is the one thing we
know renders reliably on this machine).  It is muted, has no title bar and is
stopped whenever the guide is not on screen.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QWidget

try:
    import vlc
except ImportError:                                     # pragma: no cover
    vlc = None

log = logging.getLogger("preview")


class ChannelPreview(QObject):
    """Muted, borderless libvlc player bound to a small child widget."""

    def __init__(self, widget: QWidget):
        super().__init__(widget)
        self._widget = widget
        self._instance = None
        self._player = None
        self._src: Optional[str] = None
        self._seek_target = (0.0, 0.0)
        self._ready_not_before = 0.0
        self._ready_deadline = 0.0

    # ── setup ────────────────────────────────────────────────────────────

    def _ensure(self) -> bool:
        if self._player is not None:
            return True
        if vlc is None:
            return False
        try:
            self._instance = vlc.Instance(
                "--no-audio", "--quiet", "--no-video-title-show", "--no-stats",
                # same 16:10 treatment as the main player (v0.6.1): the crop
                # filter only works at instance level on this VLC build
                "--video-filter=crop", "--crop=16:10")
            self._player = self._instance.media_player_new()
            self._player.set_hwnd(int(self._widget.winId()))
            return True
        except Exception as e:                          # never take the guide down
            log.warning("preview player unavailable: %s", e)
            self._player = None
            return False

    # ── playback ─────────────────────────────────────────────────────────

    def play(self, src: str, start_s: float = 0.0, duration_s: float = 0.0) -> bool:
        """Show `src` at `start_s` (seconds) — the channel's live position."""
        if not src or not self._ensure():
            return False
        if src == self._src and self._player.is_playing():
            # same channel — just re-aim, don't reload (avoids a black flash
            # when the cursor moves away and back)
            self._seek_target = (start_s, duration_s)
            self._apply_seek()
            return True
        self._src = src
        self._seek_target = (start_s, duration_s)
        # v0.7.0: the guide keeps the native video widget hidden until this
        # says the picture is really the join position.  Without it the panel
        # showed frame 0 (or the previous channel) until the seek landed.
        self._ready_not_before = time.time() + 0.45
        self._ready_deadline = time.time() + 4.0
        try:
            media = self._instance.media_new(src)
            media.add_options(":no-audio", ":no-video-title-show")
            self._player.set_media(media)
            self._player.play()
            # the aspect has to be set through the runtime API (media options
            # are ignored by this build), twice because the vout starts late
            QTimer.singleShot(0, self._apply_aspect)
            QTimer.singleShot(400, self._apply_aspect)
        except Exception as e:
            log.warning("preview play failed for %s: %s", src, e)
            return False
        # libvlc ignores seeks until the stream is seekable; try twice.
        QTimer.singleShot(400, self._apply_seek)
        QTimer.singleShot(1100, self._apply_seek)
        return True

    def is_ready(self) -> bool:
        """True when the preview is showing the join position (or never will)."""
        if self._player is None:
            return False
        now = time.time()
        if now < self._ready_not_before:
            return False
        if now > self._ready_deadline:
            return True
        target, duration = self._seek_target
        try:
            if not self._player.is_playing():
                return False
            t = (self._player.get_time() or 0) / 1000.0
        except Exception:
            return True
        if target <= 2.0:
            return t >= 0.35
        return t > 0 and abs(t - target) <= max(6.0, duration * 0.01)

    def _apply_aspect(self):
        if self._player is None:
            return
        try:
            self._player.video_set_aspect_ratio("16:10")
        except Exception:
            pass

    def _apply_seek(self):
        if self._player is None:
            return
        target, duration = self._seek_target
        if target <= 1.0 or duration <= target:
            return
        frac = min(0.98, target / duration)
        try:
            current = self._player.get_position() or 0.0
            if abs(current - frac) > 0.02:
                self._player.set_position(frac)
        except Exception:
            pass

    def stop(self):
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass
        self._src = None
        self._seek_target = (0.0, 0.0)

    def release(self):
        self.stop()
        if self._player is not None:
            try:
                self._player.release()
            except Exception:
                pass
            self._player = None
        if self._instance is not None:
            try:
                self._instance.release()
            except Exception:
                pass
            self._instance = None
