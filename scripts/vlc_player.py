"""
vlc_player.py — python-vlc wrapper for PROJECT:CRT (Windows 11 path)

Wraps libvlc to:
  1. Render video into a PySide6 QWidget on Windows via set_hwnd(winId)
  2. Apply per-channel deinterlace mode (none / yadif / yadif2x / ivtc / bob)
  3. Force 4:3 aspect ratio so the Aiwa VX-D2120 CRT is correctly letterboxed
  4. Emit Qt signals on media state changes so the UI can react
     (ended → advance queue; playing/paused → overlay visibility; etc.)

No CRT shader is applied — the real phosphor/scanline of the Aiwa VX-D2120
provides the CRT look. Adding a glsl-shader would double-apply the effect.
"""

from __future__ import annotations

import sys
import time
import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtWidgets import QWidget

# python-vlc — thin ctypes binding around libvlc.dll on Windows.
# Requires VLC to be installed at C:\\Program Files\\VideoLAN\\VLC\\
try:
    import vlc
except ImportError as e:
    raise ImportError(
        "python-vlc not installed. Run: pip install python-vlc\n"
        "Also ensure VLC Media Player is installed (https://www.videolan.org/).\n"
        f"Original error: {e}"
    ) from e


log = logging.getLogger("vlc_player")


# VLC deinterlace mode names accepted by libvlc. See:
#   https://wiki.videolan.org/Deinterlacing/
# Mode names correspond to VLC's --deinterlace-mode option.
VALID_DEINTERLACE_MODES = {
    "none", "bob", "linear", "blend", "yadif", "yadif2x", "phosphor", "ivtc",
}


class VlcPlayer(QObject):
    """Wraps a libvlc MediaPlayer bound to a Qt widget on Windows.

    Signals:
        started()       — playback of the current media started
        paused()        — playback paused
        resumed()       — playback resumed after pause
        ended()         — current media finished; advance the queue
        error(message)  — playback error (string message)
        position(p)     — playback position in [0,1], emitted ~4x/second
        length_ms(ms)   — media length in milliseconds, known once playback starts
    """

    started = Signal()
    paused = Signal()
    resumed = Signal()
    ended = Signal()
    error = Signal(str)
    position = Signal(float)
    length_ms = Signal(int)

    def __init__(self, video_widget: QWidget, parent: Optional[QObject] = None,
                 crop: str = "", level_audio: bool = True):
        super().__init__(parent)
        self.widget = video_widget

        # libvlc setup
        # v0.6.1: `crop` is applied with the crop FILTER at instance level.
        # Measured on this machine (VLC 3.0.20):
        #   :crop=16:10 as a media option      -> parsed as a 16x10 pixel box
        #                                          (extreme zoom)
        #   video_set_crop_geometry("16:10")    -> accepted, no effect
        #   --video-filter=crop --crop=16:10    -> real crop, proportions kept
        args = ["--no-video-title-show", "--no-stats", "--quiet"]
        if crop:
            args += ["--video-filter=crop", f"--crop={crop}"]
        # v0.7.0: level the volume between programmes and commercials.  Ad
        # reels are mastered much louder than 2003 TV captures, so switching
        # between them is a jump.  `normvol` is VLC's built-in normaliser; if a
        # build lacks the module, VLC logs a warning and plays normally.
        if level_audio:
            args += ["--audio-filter=normvol"]
        self._instance = vlc.Instance(*args)
        self._player = self._instance.media_player_new()

        # Bind to the Qt widget's window handle. Platform-specific:
        #   Windows: set_hwnd(int(winId()))
        #   Linux X11: set_xwindow(int(winId()))
        #   macOS: set_nsobject(int(winId()))  # needs an NSView, more involved
        self._bind_widget()

        # Hook VLC event callbacks → emit Qt signals
        self._event_manager = self._player.event_manager()
        self._attach_events()

        # Polling timer for position updates (libvlc doesn't push these as events)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)  # 4 Hz
        self._poll_timer.timeout.connect(self._poll)
        self._current_length_ms = 0

        # State tracking
        self._current_media = None
        self._current_src = None   # path of the media currently loaded (v0.3.4)
        self._current_deinterlace = "none"
        self._current_aspect = "4:3"
        self._current_crop = crop or "16:10"

    # ── Platform binding ─────────────────────────────────────────────────

    def _bind_widget(self):
        win_id = int(self.widget.winId())
        if sys.platform == "win32":
            self._player.set_hwnd(win_id)
        elif sys.platform.startswith("linux"):
            self._player.set_xwindow(win_id)
        elif sys.platform == "darwin":
            # On macOS you typically need an NSView, not just the Qt widget's id.
            # For a Qt widget, you can get the NSView via QtWin + winId():
            try:
                from PySide6.QtWinExtras import QtWin  # type: ignore
                view = QtWin.fromHWND(win_id)  # placeholder — needs proper NSView plumbing
                self._player.set_nsobject(int(view))
            except ImportError:
                log.warning("macOS binding not fully implemented; video may not embed.")
        else:
            log.warning("Unsupported platform for video embedding: %s", sys.platform)

    # ── VLC events → Qt signals ──────────────────────────────────────────

    def _attach_events(self):
        from vlc import EventType

        em = self._event_manager
        em.event_attach(EventType.MediaPlayerPlaying, self._on_playing)
        em.event_attach(EventType.MediaPlayerPaused, self._on_paused)
        em.event_attach(EventType.MediaPlayerEndReached, self._on_end)
        em.event_attach(EventType.MediaPlayerEncounteredError, self._on_error)
        em.event_attach(EventType.MediaPlayerLengthChanged, self._on_length)

    def _on_playing(self, event):
        log.debug("VLC: playing")
        self.started.emit()

    def _on_paused(self, event):
        log.debug("VLC: paused")
        self.paused.emit()

    def _on_end(self, event):
        log.debug("VLC: end reached")
        self.ended.emit()

    def _on_error(self, event):
        msg = "VLC playback error"
        log.error(msg)
        self.error.emit(msg)

    def _on_length(self, event):
        # libvlc can fire LengthChanged for the OUTGOING media right after
        # set_media(), which used to leave the progress bar showing the
        # previous video's length.  Ignore anything in that window, then pick
        # the real length up again shortly afterwards.
        if time.monotonic() < getattr(self, "_length_guard_until", 0.0):
            log.debug("VLC: ignoring stale length event")
            return
        length = self._player.get_length()
        if length and length > 0:
            self._current_length_ms = length
            self.length_ms.emit(length)

    def _poll(self):
        if self._player.is_playing():
            length = self._player.get_length() or self._current_length_ms
            if length > 0:
                pos = self._player.get_position()  # [0,1]
                self.position.emit(pos)

    # ── Public API ──────────────────────────────────────────────────────

    def play_item(self, src: str, deinterlace: str = "none", aspect: str = "4:3",
                  crop: str = ""):
        """Load and play a media file with per-item VLC options.

        Args:
            src:          Path or URL to the media file.
            deinterlace:  One of VALID_DEINTERLACE_MODES.
            aspect:       Display shape, applied through
                          video_set_aspect_ratio() — media options are ignored
                          by this VLC build (measured).
            crop:         Crop geometry for this item (v0.7.3).  The instance is
                          created with --crop=16:10; this re-applies the value
                          for files that override it.  Ignored by builds that
                          do not honour the runtime call.

        The instance-level crop stays 16:10; per-item crop is attempted at
        runtime (see _apply_crop).
        """
        if deinterlace not in VALID_DEINTERLACE_MODES:
            log.warning("Unknown deinterlace mode '%s'; falling back to 'none'", deinterlace)
            deinterlace = "none"

        self._current_deinterlace = deinterlace
        self._current_aspect = aspect

        # Build the media with per-item options
        self._current_src = src
        self._current_media = self._instance.media_new(src)

        opts = []
        if deinterlace != "none":
            opts += [f":deinterlace-mode={deinterlace}", "deinterlace=1"]

        # Reset length so we get the new length from VLC
        self._current_length_ms = 0
        self._length_guard_until = time.monotonic() + 0.5

        self._current_media.add_options(*opts)
        self._player.set_media(self._current_media)
        self._player.play()
        self._poll_timer.start()
        self._apply_aspect(aspect)
        if crop:
            self._apply_crop(crop)
        # Re-read once the guard has expired (the LengthChanged event for this
        # media may have been swallowed by it).
        QTimer.singleShot(700, self._refresh_length)

    def _apply_aspect(self, aspect: str):
        """Set the display aspect through the runtime API.

        The `:aspect-ratio=` media option has no effect on this VLC build, but
        video_set_aspect_ratio() does.  The vout may still be starting when
        play() returns, so it is retried shortly after.
        """
        if not aspect:
            return
        for delay in (0, 350, 1200):
            QTimer.singleShot(delay, lambda a=aspect: self._safe_aspect(a))

    def _safe_aspect(self, aspect: str):
        try:
            self._player.video_set_aspect_ratio(aspect)
        except Exception:
            pass

    def _apply_crop(self, crop: str) -> None:
        """Apply a crop geometry; the vout may still be starting, so retry."""
        if not crop:
            return
        self._current_crop = crop
        for delay in (0, 350, 1200):
            QTimer.singleShot(delay, lambda c=crop: self._safe_crop(c))

    def _safe_crop(self, crop: str):
        try:
            self._player.video_set_crop_geometry(crop)
        except Exception:
            pass

    def set_crop(self, crop: str) -> None:
        """Change the crop geometry at runtime (hotkey C / per-file override).

        libvlc exposes this through `video_set_crop_geometry()`; whether a given
        build actually honours it has to be checked on hardware.  If it does not,
        nothing breaks — the next item re-applies its own crop.
        """
        self._current_crop = crop
        self._safe_crop(crop)

    def set_aspect(self, aspect: str) -> None:
        """Change the display aspect of the current media at runtime.

        Used by the per-file aspect override (v0.7.1).  The *crop* is an instance
        option and cannot change here, but the display aspect can — measured on
        this build, `video_set_aspect_ratio()` is the call that works.
        """
        self._current_aspect = aspect
        self._safe_aspect(aspect)

    def _refresh_length(self):
        try:
            length = self._player.get_length()
        except Exception:
            return
        if length and length > 0:
            self._current_length_ms = length
            self.length_ms.emit(length)

    def set_logo(self, path: str, x: int, y: int, opacity: int = 128):
        """Kept for callers that still ask for it; renders nothing on Windows
        with VLC 3.0.x (verified) — VideoOverlay does the logo now."""
        log.debug("set_logo() called (%s) but VLC's logo sub-source does not "
                  "render here; ignoring", path)

    def clear_logo(self):
        pass

    def pause(self):
        self._player.pause()

    def set_pause(self, val: int):
        """0 = play, 1 = pause."""
        self._player.set_pause(val)

    def set_time(self, time_ms: int):
        """Seek to an absolute time (ms). NOTE: goes through the container's own
        timestamps — on MPEG-PS with broken timestamps it lands in the wrong
        place (asked for 900 s, got 20 s). Prefer seek_to(fraction) for those."""
        self._player.set_time(time_ms)

    def get_time_ms(self) -> int:
        """Playback position in milliseconds, 0 while nothing is loaded.

        This is *real* media time even when get_length() is wrong (verified on
        the 44-minute MPEG-PS that libvlc reports as 37 hours).
        """
        return int(self._player.get_time() or 0)

    def show_marquee(self, text: str, size: int = 20,
                     color: int = 0xFFFFFF, opacity: int = 255):
        """Show text overlay using VLC's marquee sub-source (renders INTO video).
        Text is CENTERED on screen automatically via VLC's Position option."""
        try:
            from vlc import VideoMarqueeOption
            self._player.video_set_marquee_int(VideoMarqueeOption.Enable, 1)
            self._player.video_set_marquee_string(VideoMarqueeOption.Text, text)
            # Position 0 = center of screen (VLC handles x/y automatically)
            self._player.video_set_marquee_int(VideoMarqueeOption.Position, 0)
            self._player.video_set_marquee_int(VideoMarqueeOption.Size, size)
            self._player.video_set_marquee_int(VideoMarqueeOption.Color, color)
            self._player.video_set_marquee_int(VideoMarqueeOption.Opacity, opacity)
        except Exception as e:
            log.warning(f"Marquee not available: {e}")

    def hide_marquee(self):
        """Hide the VLC marquee text overlay."""
        try:
            from vlc import VideoMarqueeOption
            self._player.video_set_marquee_int(VideoMarqueeOption.Enable, 0)
        except Exception:
            pass

    def resume(self):
        if not self._player.is_playing():
            self._player.play()
            self.resumed.emit()

    def stop(self):
        self._poll_timer.stop()
        self._player.stop()

    def set_volume(self, percent: int):
        """0-100 (or higher for amplification)."""
        self._player.audio_set_volume(max(0, min(200, int(percent))))

    def seek_to(self, fraction: float):
        if 0.0 <= fraction <= 1.0:
            self._player.set_position(fraction)

    def current_position(self) -> float:
        return self._player.get_position() or 0.0

    def current_length_ms(self) -> int:
        return self._current_length_ms

    def current_src(self) -> Optional[str]:
        """Path passed to the most recent play_item() — lets callers verify that
        a reported length belongs to the media they think is playing."""
        return self._current_src

    def current_deinterlace(self) -> str:
        return self._current_deinterlace

    def current_aspect(self) -> str:
        return self._current_aspect

    def release(self):
        """Tear down libvlc. Call on app shutdown."""
        self._poll_timer.stop()
        self._player.stop()
        self._player.release()
        self._instance.release()
