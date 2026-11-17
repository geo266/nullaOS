"""
settings.py — tiny persisted settings store (settings.json, project root)

Everything the user can change from the SETTINGS screen lives here: the clock
offset, the 12/24-hour preference, whether ad pods are generated at all.  The
file is optional — missing or corrupt just means "defaults".

Kept Qt-free so the timeline/clock tests can run without a display.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("settings")

SETTINGS_FILE = "settings.json"

DEFAULTS: dict[str, Any] = {
    "clock_offset_s": 0.0,   # manual clock shift, seconds (VCR-style set time)
    "clock_24h": True,       # 24-hour readouts in the guide / OSD
    "ads_enabled": True,     # False = no commercial pods anywhere
}


class Settings:
    """A dict with defaults and a JSON file behind it."""

    def __init__(self, path: Path | str, data: dict | None = None):
        self.path = Path(path)
        self._data = dict(DEFAULTS)
        if data:
            self._data.update({k: v for k, v in data.items() if k in DEFAULTS})

    # ── loading ───────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path | str) -> "Settings":
        path = Path(path)
        data: dict = {}
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    data = raw
            except Exception as e:
                log.warning("Could not read %s (%s) — using defaults", path.name, e)
        return cls(path, data)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            tmp.replace(self.path)
        except Exception as e:
            log.warning("Could not save %s: %s", self.path.name, e)

    # ── access ────────────────────────────────────────────────────────────

    def get(self, key: str, default=None):
        if key in self._data:
            return self._data[key]
        return DEFAULTS.get(key, default)

    def set(self, key: str, value, save: bool = True) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        if save:
            self.save()

    def as_dict(self) -> dict:
        return dict(self._data)
