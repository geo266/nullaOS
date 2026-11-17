"""test_display.py — per-file aspect/crop overrides (no Qt).

Run:  python scripts/test_display.py

The hotkeys (A aspect, C crop) write here; a wrong merge would either forget the
choice or wipe the other dimension of the same file, so the rules are pinned.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.display import (                                   # noqa: E402
    ASPECT_PRESETS, CROP_PRESETS, DisplayOverrides,
)

#: Some tests just need an in-memory-ish store; point it at the temp dir so a
#: stray `unused.json` is never written into the project (or shipped).
_SCRATCH = Path(tempfile.gettempdir()) / "nulla_test_display.json"


class AspectTests(unittest.TestCase):
    def test_cycle_and_default(self):
        d = DisplayOverrides(_SCRATCH)
        self.assertIsNone(d.get("x.mp4", "aspect"))
        self.assertEqual(d.next_preset("x.mp4", "aspect"), "16:9")
        self.assertEqual(d.next_preset("x.mp4", "aspect"), "4:3")
        for expected in ("2.21:1", "1.85:1", "16:10"):
            self.assertEqual(d.next_preset("x.mp4", "aspect"), expected)
        self.assertEqual(d.next_preset("x.mp4", "aspect"), "auto")
        self.assertIsNone(d.get("x.mp4", "aspect"))      # back to auto = no entry

    def test_auto_clears_the_entry(self):
        d = DisplayOverrides(_SCRATCH)
        d.set("x.mp4", "aspect", "2.21:1")
        self.assertEqual(d.get("x.mp4", "aspect"), "2.21:1")
        d.set("x.mp4", "aspect", "auto")
        self.assertIsNone(d.get("x.mp4", "aspect"))


class CropTests(unittest.TestCase):
    def test_cycle_starts_at_the_instance_default(self):
        d = DisplayOverrides(_SCRATCH)
        self.assertIsNone(d.get("x.mp4", "crop"))
        self.assertEqual(d.next_preset("x.mp4", "crop"), "16:9")
        self.assertEqual(d.get("x.mp4", "crop"), "16:9")
        self.assertEqual(d.next_preset("x.mp4", "crop"), "4:3")
        for expected in ("1.85:1", "2.21:1", "16:10"):
            self.assertEqual(d.next_preset("x.mp4", "crop"), expected)
        self.assertIsNone(d.get("x.mp4", "crop"))        # back to 16:10 = no entry

    def test_both_dimensions_are_independent(self):
        d = DisplayOverrides(_SCRATCH)
        d.set("x.mp4", "aspect", "2.21:1")
        d.set("x.mp4", "crop", "16:9")
        self.assertEqual(d.get("x.mp4", "aspect"), "2.21:1")
        self.assertEqual(d.get("x.mp4", "crop"), "16:9")
        d.set("x.mp4", "aspect", "auto")                 # clears aspect only
        self.assertIsNone(d.get("x.mp4", "aspect"))
        self.assertEqual(d.get("x.mp4", "crop"), "16:9")


class PersistenceTests(unittest.TestCase):
    def test_roundtrip_keeps_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "display_overrides.json"
            d = DisplayOverrides(path)
            d.set("X.mp4", "aspect", "1.85:1")
            d.set("X.mp4", "crop", "4:3")
            again = DisplayOverrides.load(path)
            key = DisplayOverrides.key("X.mp4")
            self.assertEqual(again.get(key, "aspect"), "1.85:1")
            self.assertEqual(again.get(key, "crop"), "4:3")

    def test_legacy_string_is_read_as_aspect(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "display_overrides.json"
            path.write_text(json.dumps({"Y.mp4": "2.21:1"}), encoding="utf-8")
            d = DisplayOverrides.load(path)
            key = DisplayOverrides.key("Y.mp4")
            self.assertEqual(d.get(key, "aspect"), "2.21:1")
            self.assertIsNone(d.get(key, "crop"))

    def test_unknown_presets_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "display_overrides.json"
            path.write_text(json.dumps({"Z.mp4": {"aspect": "9:16", "crop": "banana"}}),
                            encoding="utf-8")
            d = DisplayOverrides.load(path)
            self.assertEqual(d.as_dict(), {})

    def test_path_keys_are_normalised(self):
        a = DisplayOverrides.key("C:/Media/a.mp4")
        b = DisplayOverrides.key(r"C:\Media\a.mp4")
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
