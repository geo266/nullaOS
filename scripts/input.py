"""
input.py — Unified input router for keyboard + gamepad

Translates BOTH keyboard events (from Qt's keyPressEvent) AND gamepad events
(from pygame polling on a QTimer) into a single stream of abstract actions:
    "up", "down", "left", "right", "enter", "back", "play_pause", "guide",
    "menu", "info", "vault"

Each screen implements handle_input(action: str) and decides what to do.
The MainWindow routes the current screen's handle_input on each action.

Gamepad mapping (configurable below):
    D-pad up/down/left/right -> up/down/left/right
    A button (button 0)     -> enter
    B button (button 1)     -> back
    Start button (button 9)  -> play_pause
    Back button (button 8)   -> guide

Keyboard mapping (the user's spec):
    Arrow Up/Down            -> up/down (channel switch OR guide browse, screen-dependent)
    Arrow Left/Right         -> left/right (mode toggle on boot, FF/RW in live)
    Enter                    -> enter (select)
    Backspace                -> back (exit guide / back to live)
    Space                    -> play_pause (pause/resume)

If pygame isn't installed or no gamepad is connected, the InputController
just no-ops the polling loop and keyboard works as the only input source.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal, Qt

try:
    import pygame
    _HAS_PYGAME = True
except ImportError:
    pygame = None
    _HAS_PYGAME = False

log = logging.getLogger("input")


# ── Keyboard defaults ───────────────────────────────────────────────────────
# action -> Qt key.  The user can rebind any of these from SETTINGS (M > SETTINGS
# > HOTKEYS); the bindings are stored in settings.json and passed back in.
DEFAULT_KEY_MAP: dict[str, int] = {
    "up":        Qt.Key_Up,
    "down":      Qt.Key_Down,
    "left":      Qt.Key_Left,
    "right":     Qt.Key_Right,
    "enter":     Qt.Key_Return,
    "back":      Qt.Key_Backspace,
    "play_pause": Qt.Key_Space,
    "guide":     Qt.Key_G,
    "menu":      Qt.Key_M,
    "info":      Qt.Key_I,
    "vault":     Qt.Key_V,
    "picker":    Qt.Key_P,
    "vol_up":    Qt.Key_Plus,
    "vol_down":  Qt.Key_Minus,
    "aspect":    Qt.Key_A,
    "crop":      Qt.Key_C,
    "quit":      Qt.Key_Q,
}

# Keys that should always mean the same as another binding.
ALIAS_KEYS = {
    Qt.Key_Enter: Qt.Key_Return,      # numpad Enter
    Qt.Key_Escape: Qt.Key_Backspace,  # convenience back
    Qt.Key_Equal: Qt.Key_Plus,        # '+' without shift on many layouts
    Qt.Key_Underscore: Qt.Key_Minus,
}


# ── Gamepad button → action mapping (Xbox-style 0-9 indices) ─────────────────
GAMEPAD_BUTTON_MAP = {
    0: "enter",       # A
    1: "back",        # B
    8: "guide",       # Back/View (the smaller button next to Start)
    9: "play_pause",  # Start/Menu
}

# Gamepad axis threshold for D-pad emulation
AXIS_DEADZONE = 0.5


class InputController(QObject):
    """Singleton-style input router. Polls pygame for gamepad events at 60 Hz
    and translates Qt keyboard events from the MainWindow's keyPressEvent.

    Signals:
        action_emitted(str) — fired for each input action. Subscribers
        (the MainWindow) route this to the current screen's handle_input.
    """

    action_emitted = Signal(str)

    def __init__(self, parent: Optional[QObject] = None, bindings: Optional[dict] = None):
        super().__init__(parent)

        # Keyboard bindings (v0.7.0: remappable, see SETTINGS > HOTKEYS)
        self.key_map: dict[str, int] = dict(DEFAULT_KEY_MAP)
        if bindings:
            for action, key in bindings.items():
                if action in self.key_map:
                    try:
                        self.key_map[action] = int(key)
                    except (TypeError, ValueError):
                        pass
        self._rebuild_reverse_map()
        self._capture_cb = None

        # Gamepad state
        self._gamepad = None
        self._prev_buttons: set[int] = set()
        self._prev_hat = (0, 0)
        self._prev_axes: dict[int, float] = {}

        # Init pygame if available
        if _HAS_PYGAME:
            try:
                pygame.init()
                # Don't init video — we're just polling joysticks
                pygame.joystick.init()
                joystick_count = pygame.joystick.get_count()
                log.info("pygame detected %d joystick(s)", joystick_count)
                if joystick_count > 0:
                    self._gamepad = pygame.joystick.Joystick(0)
                    self._gamepad.init()
                    log.info("Gamepad connected: %s", self._gamepad.get_name())
            except Exception as e:
                log.warning("pygame init failed: %s — gamepad disabled", e)
                self._gamepad = None

        # Polling timer
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)  # 20 Hz — fast enough for D-pad
        self._poll_timer.timeout.connect(self._poll_gamepad)
        if self._gamepad is not None:
            self._poll_timer.start()

    # ── Keyboard → action translation ──────────────────────────────────────

    def _rebuild_reverse_map(self):
        self._key_to_action = {int(key): action for action, key in self.key_map.items()}

    def set_binding(self, action: str, key: int) -> None:
        """Rebind `action` to `key` (called from SETTINGS > HOTKEYS)."""
        if action not in self.key_map:
            return
        self.key_map[action] = int(key)
        self._rebuild_reverse_map()

    def capture_next_key(self, callback) -> None:
        """Next raw key press goes to `callback(key)` instead of an action."""
        self._capture_cb = callback

    def handle_qt_key(self, key: int) -> bool:
        """Called by MainWindow.keyPressEvent. Returns True if the key was
        recognized and translated into an action; False otherwise."""
        if self._capture_cb is not None:
            cb, self._capture_cb = self._capture_cb, None
            try:
                cb(int(key))
            except Exception as e:
                log.warning("Key capture failed: %s", e)
            return True

        lookup = ALIAS_KEYS.get(key, key)
        action = self._key_to_action.get(lookup)
        if action is None:
            return False
        self.action_emitted.emit(action)
        return True

    # ── Gamepad polling ─────────────────────────────────────────────────────

    def _poll_gamepad(self):
        if not _HAS_PYGAME or self._gamepad is None:
            return
        try:
            pygame.event.pump()  # process internal event queue

            # D-pad / hat (some controllers expose hat 0 as the D-pad)
            if self._gamepad.get_numhats() > 0:
                hat_x, hat_y = self._gamepad.get_hat(0)
                if (hat_x, hat_y) != self._prev_hat:
                    # Emit hat-change events as discrete actions
                    if hat_x != self._prev_hat[0]:
                        if hat_x < 0:
                            self.action_emitted.emit("left")
                        elif hat_x > 0:
                            self.action_emitted.emit("right")
                    if hat_y != self._prev_hat[1]:
                        if hat_y > 0:
                            self.action_emitted.emit("up")
                        elif hat_y < 0:
                            self.action_emitted.emit("down")
                    self._prev_hat = (hat_x, hat_y)
            else:
                # Fall back to left analog stick for D-pad emulation
                if self._gamepad.get_numaxes() >= 2:
                    ax = self._gamepad.get_axis(0)
                    ay = self._gamepad.get_axis(1)
                    # Left/right
                    if ax > AXIS_DEADZONE and self._prev_axes.get(0, 0.0) <= AXIS_DEADZONE:
                        self.action_emitted.emit("right")
                    elif ax < -AXIS_DEADZONE and self._prev_axes.get(0, 0.0) >= -AXIS_DEADZONE:
                        self.action_emitted.emit("left")
                    # Up/down (Y axis is inverted on most gamepads)
                    if ay < -AXIS_DEADZONE and self._prev_axes.get(1, 0.0) >= -AXIS_DEADZONE:
                        self.action_emitted.emit("up")
                    elif ay > AXIS_DEADZONE and self._prev_axes.get(1, 0.0) <= AXIS_DEADZONE:
                        self.action_emitted.emit("down")
                    self._prev_axes[0] = ax
                    self._prev_axes[1] = ay

            # Buttons
            if self._gamepad.get_numbuttons() > 0:
                pressed: set[int] = set()
                for i in range(self._gamepad.get_numbuttons()):
                    if self._gamepad.get_button(i):
                        pressed.add(i)
                # Emit on rising edge only (so press = one action, not held)
                for btn in pressed - self._prev_buttons:
                    action = GAMEPAD_BUTTON_MAP.get(btn)
                    if action:
                        self.action_emitted.emit(action)
                self._prev_buttons = pressed

        except Exception as e:
            log.warning("Gamepad poll error: %s", e)

    def shutdown(self):
        self._poll_timer.stop()
        if _HAS_PYGAME and self._gamepad is not None:
            try:
                self._gamepad.quit()
            except Exception:
                pass
