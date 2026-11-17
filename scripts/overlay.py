"""
overlay.py — transparent layer that can paint ON TOP of the VLC video surface

Why this exists
---------------
libvlc on Windows renders into its own child HWND.  Two consequences, both
verified on this machine (VLC 3.0.20, d3d11/d3d9/gl/directdraw/wingdi — all
the same):

  * A normal Qt widget (painted by its parent) is always BEHIND the video.
  * A widget with WA_NativeWindow gets its own HWND, but VLC nests a second
    window ("VLC video output") inside the video widget, so the overlay is
    still covered — only a 20 px sliver outside VLC's client area showed.
  * VLC's own logo sub-source (--sub-source=logo + video_set_logo_string)
    does not render at all here: the API succeeds and no pixels appear.

What does work is a separate frameless window with per-pixel alpha, kept
always-on-top and exactly over the video area.  Measured: 720x480 repaint in
~0.6 ms, 96 % pixel coverage over the video, and it never takes focus.

So every overlay in the app (channel logo, progress bar, PAUSED, DDR info
card, tuning snow) is painted by this window instead of by the screen widget.
That also means the video widget no longer has to be resized to "make room"
for the bar — the bar can simply sit on top of the picture, like a real OSD.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget


class VideoOverlay(QWidget):
    """Frameless, always-on-top canvas tracking `host`'s rect.

    v0.6.5: it also carries the window drag.  The picture on the Live screen is
    a native libvlc child window, so a mouse press over it goes to VLC and never
    reaches Qt; this window sits on top of the picture, so it does get the press
    and hands it to MainWindow.begin_window_drag().  Nothing else in the app
    uses the mouse, so swallowing clicks here costs nothing.
    """

    SYNC_INTERVAL_MS = 250       # safety net for window moves / DPI changes

    def __init__(self, host: QWidget):
        super().__init__(None)
        self._host = host
        self._renderer: Optional[Callable[[QPainter, int, int], None]] = None
        self._active = False
        self._dragger = None                 # MainWindow, set by set_drag_target()
        self._drag_anchor: Optional[QPoint] = None
        # None = unknown (app just started) → treat as active.  Once the host
        # reports a deactivation the overlay hides: an always-on-top window that
        # now accepts clicks must never sit invisibly over another app.
        self._host_active: Optional[bool] = None

        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        # No title bar anywhere: an open hand over the picture is the only hint
        # that the window can be picked up and moved.
        self.setCursor(Qt.OpenHandCursor)

        # Keep the overlay glued to the host even if it is moved or resized
        # without a resize event reaching this widget (frameless windows).
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(self.SYNC_INTERVAL_MS)
        self._sync_timer.timeout.connect(self._sync_geometry)
        host.installEventFilter(self)

    # ── wiring ───────────────────────────────────────────────────────────

    def set_renderer(self, fn: Callable[[QPainter, int, int], None]) -> None:
        """`fn(painter, width, height)` draws the whole overlay in host coords."""
        self._renderer = fn
        self.refresh()

    def set_drag_target(self, target) -> None:
        """Hand mouse presses here to `target` so the host window can be moved."""
        self._dragger = target

    def set_active(self, active: bool) -> None:
        """Show/hide the overlay (only the Live screen needs it)."""
        if active == self._active and self.isVisible() == active:
            return
        self._active = active
        if active:
            # _sync_geometry() shows it only when the host window is up and the
            # app is active — never as an invisible click-catcher over another app.
            self._sync_geometry()
            if self.isVisible():
                self.raise_()
            self._sync_timer.start()
        else:
            self._sync_timer.stop()
            self.hide()

    def refresh(self) -> None:
        if self._active:
            self.update()

    # ── geometry ─────────────────────────────────────────────────────────

    def _sync_geometry(self) -> None:
        host = self._host
        if (not host or not host.isVisible() or host.isMinimized()
                or self._host_active is False):
            if self.isVisible():
                self.hide()
            return
        if self._active and not self.isVisible():
            self.show()
        top_left: QPoint = self._host.mapToGlobal(QPoint(0, 0))
        rect = QRect(top_left, self._host.size())
        if self.geometry() != rect:
            self.setGeometry(rect)

    def eventFilter(self, obj, event):
        if obj is self._host:
            etype = event.type()
            if etype in (
                event.Type.Move, event.Type.Resize, event.Type.Show,
                event.Type.Hide, event.Type.WindowStateChange,
            ):
                self._sync_geometry()
            elif etype == event.Type.WindowActivate:
                self._host_active = True
                self._sync_geometry()
            elif etype == event.Type.WindowDeactivate:
                self._host_active = False
                if self.isVisible():
                    self.hide()
        return super().eventFilter(obj, event)

    # ── dragging the host window ──────────────────────────────────────────

    def mousePressEvent(self, event):
        if (event.button() == Qt.LeftButton and self._dragger is not None
                and hasattr(self._dragger, "begin_window_drag")):
            # This window cannot take focus (keyboard must stay on the app), so
            # a click here has to bring the real window forward by hand.
            host = self._host
            if host is not None:
                host.raise_()
                host.activateWindow()
            self._drag_anchor = event.globalPosition().toPoint()
            self._dragger.begin_window_drag(self._drag_anchor)
            self.setCursor(Qt.ClosedHandCursor)
            # Capture: the window follows the cursor exactly, but a one-frame
            # sync lag must not let the cursor escape and stall the drag.
            self.grabMouse()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_anchor is not None and (event.buttons() & Qt.LeftButton):
            self._dragger.drag_window_to(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_anchor is not None:
            self._drag_anchor = None
            self.releaseMouse()
            self.setCursor(Qt.OpenHandCursor)
            self._dragger.end_window_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hideEvent(self, event):
        # Leaving the Live screen (or losing the window) mid-drag must not
        # leave the drag state armed.
        if self._drag_anchor is not None:
            self._drag_anchor = None
            self.releaseMouse()
            self.setCursor(Qt.OpenHandCursor)
            if self._dragger is not None:
                self._dragger.end_window_drag()
        super().hideEvent(event)

    # ── painting ─────────────────────────────────────────────────────────

    def paintEvent(self, event):
        if not self._renderer:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            self._renderer(painter, self.width(), self.height())
        finally:
            painter.end()

    def close_overlay(self) -> None:
        self._sync_timer.stop()
        self.close()
