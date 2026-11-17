"""
clock.py — the clock the app pretends it is

The schedule, the guide and the "what is airing now" maths all need one idea of
"now".  Until v0.7.0 that was `time.time()` scattered everywhere, so there was
nothing to set: the guide's times were invented placeholders and the only clock
in the app was Windows'.

This is a VCR-style clock: it follows the system time, plus a manual offset the
user can set from the SETTINGS screen.  Setting it forward moves the whole
broadcast day forward (every channel jumps with it, like re-setting the clock on
a real set), and the offset is remembered in settings.json.

Qt-free.
"""

from __future__ import annotations

import datetime
import time
from typing import Optional


class AppClock:
    """System time + a manual offset, with VCR-style setting."""

    def __init__(self, offset_s: float = 0.0, on_change=None):
        self._offset = float(offset_s or 0.0)
        self._on_change = on_change

    # ── reading ───────────────────────────────────────────────────────────

    @property
    def offset(self) -> float:
        return self._offset

    def now(self) -> float:
        """Epoch seconds the app believes it is."""
        return time.time() + self._offset

    def local(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.now())

    # ── setting ───────────────────────────────────────────────────────────

    def set_offset(self, offset_s: float) -> None:
        self._offset = float(offset_s)
        if self._on_change:
            self._on_change(self._offset)

    def set_wall(self, hour: int, minute: int, second: int = 0) -> None:
        """Make the app read `hour:minute:second` today (VCR: set clock)."""
        hour = int(hour) % 24
        minute = int(minute) % 60
        second = int(second) % 60
        today = datetime.date.today()
        target = datetime.datetime.combine(today, datetime.time(hour, minute, second))
        self.set_offset(target.timestamp() - time.time())

    def sync_to_system(self) -> None:
        """Back to the real time (offset 0)."""
        self.set_offset(0.0)

    # ── formatting ────────────────────────────────────────────────────────

    def format_time(self, ts: Optional[float] = None, use_24h: bool = True,
                    seconds: bool = False) -> str:
        if ts is None:
            ts = self.now()
        dt = datetime.datetime.fromtimestamp(ts)
        if use_24h:
            return dt.strftime("%H:%M:%S" if seconds else "%H:%M")
        text = dt.strftime("%I:%M:%S %p" if seconds else "%I:%M %p")
        return text[1:] if text.startswith("0") else text

    def format_day(self, ts: float, now_ts: Optional[float] = None) -> str:
        """'Today' / 'Tomorrow' / 'Sat 31' for the guide's day column."""
        dt = datetime.datetime.fromtimestamp(ts)
        now_dt = datetime.datetime.fromtimestamp(self.now() if now_ts is None else now_ts)
        days = (dt.date() - now_dt.date()).days
        if days == 0:
            return "Today"
        if days == 1:
            return "Tomorrow"
        return dt.strftime("%a %d")
