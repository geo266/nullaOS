"""
window_state.py — remember where the frameless 720x480 window was left

Why this exists
---------------
The main window is borderless (`Qt.FramelessWindowHint`) at a fixed 720x480,
because that is the Aiwa's raster.  Until v0.6.5 it could not be moved at all:
whatever position Windows picked the first time was where it stayed, which is
fine on the CRT (where 720x480 fills the tube) and wrong on a 1440p desktop
monitor, where the window is a small box in a corner.

Now it can be dragged (see MainWindow.begin_window_drag / VideoOverlay) and this
module remembers the spot **per screen**: the CRT and the desktop monitor each
keep their own position, so unplugging the tube does not lose the desktop spot
and plugging it back in does not put the window in the wrong place.

Everything here works on plain tuples and is Qt-free, so
`scripts/test_window_state.py` runs without a display.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("window_state")

WINDOW_STATE_FILE = "window_state.json"
#: How much of the window must overlap a screen for us to leave it alone.
MIN_VISIBLE_PX = 80


# ── geometry (plain tuples: (x, y, w, h)) ───────────────────────────────────

def clamp_to_rect(position: tuple[int, int], size: tuple[int, int],
                  rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """Keep a window of `size` inside `rect` (a screen's available area).

    A window larger than the screen is pinned to the screen's top-left corner
    instead of being centred off both edges.
    """
    x, y = int(position[0]), int(position[1])
    w, h = int(size[0]), int(size[1])
    rx, ry, rw, rh = (int(v) for v in rect)

    if w >= rw:
        x = rx
    else:
        x = min(max(x, rx), rx + rw - w)

    if h >= rh:
        y = ry
    else:
        y = min(max(y, ry), ry + rh - h)
    return x, y


def center_in_rect(size: tuple[int, int],
                   rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """Top-left position that centres a window of `size` in `rect`."""
    w, h = int(size[0]), int(size[1])
    rx, ry, rw, rh = (int(v) for v in rect)
    return rx + max(0, (rw - w) // 2), ry + max(0, (rh - h) // 2)


def find_screen(screens: list[dict], name: str) -> Optional[dict]:
    for scr in screens:
        if scr.get("name") == name:
            return scr
    return None


def primary_screen(screens: list[dict]) -> Optional[dict]:
    for scr in screens:
        if scr.get("primary"):
            return scr
    return screens[0] if screens else None


def is_on_any_screen(position: tuple[int, int], size: tuple[int, int],
                     screens: list[dict], min_visible: int = MIN_VISIBLE_PX) -> bool:
    """True when at least `min_visible` px of the window lands on some screen."""
    x, y = int(position[0]), int(position[1])
    w, h = int(size[0]), int(size[1])
    for scr in screens:
        ax, ay, aw, ah = (int(v) for v in scr["available"])
        overlap_w = min(x + w, ax + aw) - max(x, ax)
        overlap_h = min(y + h, ay + ah) - max(y, ay)
        if overlap_w >= min_visible and overlap_h >= min_visible:
            return True
    return False


def pick_position(saved: Optional[dict], screens: list[dict],
                  size: tuple[int, int]) -> tuple[int, int]:
    """Where the window should open.

    1. the screen it was last on, at the same spot (clamped so it can't hang
       off the edge after a resolution change),
    2. else the primary screen at that spot,
    3. else the primary screen, centred.
    """
    screens = screens or []
    primary = primary_screen(screens)
    saved = saved or {}

    x, y = saved.get("x"), saved.get("y")
    have_pos = isinstance(x, (int, float)) and isinstance(y, (int, float))

    target = find_screen(screens, str(saved.get("screen") or "")) or primary
    if target is None:
        return (int(x or 0), int(y or 0)) if have_pos else (0, 0)

    if have_pos:
        return clamp_to_rect((int(x), int(y)), size, target["available"])

    return center_in_rect(size, target["available"])


# ── persistence ─────────────────────────────────────────────────────────────

def load(path: Path | str) -> dict:
    """Read window_state.json. Missing/corrupt file = empty dict (first run)."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        log.warning("Could not read %s (%s) — using defaults", path.name, e)
        return {}


def save(path: Path | str, screen_name: str, x: int, y: int) -> None:
    """Write the window's spot. Never raises — a lost position is not fatal."""
    path = Path(path)
    data = {"screen": str(screen_name or ""), "x": int(x), "y": int(y)}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)          # atomic on the same volume
    except Exception as e:
        log.warning("Could not save %s: %s", path.name, e)
