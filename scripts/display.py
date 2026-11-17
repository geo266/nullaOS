"""
display.py — per-file display shape overrides (aspect **and** crop)

Why
---
`VlcPlayer` crops every item to 16:10 at the VLC instance level and displays it
with `video_set_aspect_ratio("16:10")`.  That is right for almost everything in
the catalog, but not for all of it: some captures only look correct with a
different crop and/or a wider display aspect.  The user found that
“crop 16:10 + aspect 2.21:1” fixes two of his commercials, while stretching
everything else.

Two independent knobs, one per hotkey:

  * **A** cycles the *display aspect* (`video_set_aspect_ratio`) — this one is
    definitely live on his build (v0.6.1 measured it).
  * **C** cycles the *crop* (`video_set_crop_geometry`).  The crop is normally an
    instance option; the runtime call is the only per-file route and may be a
    no-op on some VLC builds — see the handover.

Both are remembered per file in `display_overrides.json` in the project root.

    {"C:/Media/Kawaii/Commercials/x.mp4": {"aspect": "2.21:1", "crop": "16:9"}}

Older files with a bare string (`"…x.mp4": "2.21:1"`) are read as aspect-only.

Qt-free; `MainWindow` owns load/save, this module is just the data.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("display")

DISPLAY_FILE = "display_overrides.json"

#: Display aspect presets for the A key.  "auto" = the app default (16:10).
ASPECT_PRESETS = ["auto", "16:9", "4:3", "2.21:1", "1.85:1", "16:10"]
ASPECT_LABELS = {
    "auto": "AUTO 16:10",
    "16:9": "16:9",
    "4:3": "4:3",
    "2.21:1": "2.21:1 WIDE",
    "1.85:1": "1.85:1",
    "16:10": "16:10",
}

#: Crop presets for the C key.  "16:10" is the app default (instance option).
CROP_PRESETS = ["16:10", "16:9", "4:3", "1.85:1", "2.21:1"]
CROP_LABELS = {
    "16:10": "16:10",
    "16:9": "16:9",
    "4:3": "4:3",
    "1.85:1": "1.85:1",
    "2.21:1": "2.21:1",
}

PRESET_LABELS = dict(ASPECT_LABELS)     # backwards-compatible name


class DisplayOverrides:
    """Per-file `aspect` / `crop` overrides, persisted next to the app."""

    def __init__(self, path: Path | str, data: Optional[dict] = None):
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        for k, v in (data or {}).items():
            if not isinstance(k, str):
                continue
            if isinstance(v, str):              # legacy: aspect only
                v = {"aspect": v}
            if not isinstance(v, dict):
                continue
            entry = {}
            if v.get("aspect") in ASPECT_PRESETS and v.get("aspect") != "auto":
                entry["aspect"] = v["aspect"]
            if v.get("crop") in CROP_PRESETS and v.get("crop") != CROP_PRESETS[0]:
                entry["crop"] = v["crop"]
            if entry:
                # Normalise on load: older/hand-written files may use relative or
                # backslash paths, and get() always looks up the resolved form.
                self._data[self.key(k)] = entry

    # ── loading ───────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path | str) -> "DisplayOverrides":
        path = Path(path)
        data = {}
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    data = raw
            except Exception as e:
                log.warning("Could not read %s (%s) — no overrides", path.name, e)
        return cls(path, data)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, sort_keys=True)
            tmp.replace(self.path)
        except Exception as e:
            log.warning("Could not save %s: %s", self.path.name, e)

    # ── access ────────────────────────────────────────────────────────────

    @staticmethod
    def key(src: str) -> str:
        """Normalise a source path so the same file always maps to one key."""
        try:
            return str(Path(src).resolve()).replace("\\", "/")
        except Exception:
            return str(src)

    def get(self, src: str, kind: str = "aspect") -> Optional[str]:
        return self._data.get(self.key(src), {}).get(kind)

    def set(self, src: str, kind: str, value: Optional[str]) -> None:
        k = self.key(src)
        entry = dict(self._data.get(k, {}))
        presets = ASPECT_PRESETS if kind == "aspect" else CROP_PRESETS
        default = "auto" if kind == "aspect" else CROP_PRESETS[0]
        if not value or value == default:
            entry.pop(kind, None)
        elif value in presets:
            entry[kind] = value
        else:
            return
        if entry:
            self._data[k] = entry
        else:
            self._data.pop(k, None)
        self.save()

    def next_preset(self, src: str, kind: str = "aspect") -> str:
        """Cycle the preset for `src` in that dimension and return the new one."""
        presets = ASPECT_PRESETS if kind == "aspect" else CROP_PRESETS
        default = "auto" if kind == "aspect" else CROP_PRESETS[0]
        current = self.get(src, kind) or default
        try:
            i = presets.index(current)
        except ValueError:
            i = 0
        nxt = presets[(i + 1) % len(presets)]
        self.set(src, kind, nxt)
        return nxt

    def as_dict(self) -> dict:
        return {k: dict(v) for k, v in self._data.items()}
