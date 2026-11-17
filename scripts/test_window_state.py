"""test_window_state.py — regression tests for window placement (no Qt).

Run:  python scripts/test_window_state.py

The window is frameless and fixed at 720x480, so a wrong position means the
app opens half off the screen (or on a monitor that is no longer plugged in)
and, with no title bar, there is nothing to grab to bring it back.  These
tests pin the rules: remember per screen, clamp into the screen, centre on
first run, recover when the remembered screen is gone.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts import window_state as ws                          # noqa: E402

SIZE = (720, 480)
HD = {"name": "\\\\.\\DISPLAY1", "primary": True, "available": (0, 0, 2560, 1400)}
CRT = {"name": "\\\\.\\DISPLAY2", "primary": False, "available": (2560, 0, 720, 480)}
SCREENS = [HD, CRT]


class ClampTests(unittest.TestCase):
    def test_inside_is_untouched(self):
        self.assertEqual(ws.clamp_to_rect((100, 200), SIZE, HD["available"]), (100, 200))

    def test_off_the_left_edge_snaps_to_the_edge(self):
        self.assertEqual(ws.clamp_to_rect((-400, 50), SIZE, HD["available"]), (0, 50))

    def test_off_the_right_edge_snaps_inside(self):
        self.assertEqual(ws.clamp_to_rect((4000, 50), SIZE, HD["available"]), (1840, 50))

    def test_off_the_bottom_snaps_inside(self):
        self.assertEqual(ws.clamp_to_rect((10, 9999), SIZE, HD["available"]), (10, 920))

    def test_window_bigger_than_screen_is_pinned_top_left(self):
        self.assertEqual(ws.clamp_to_rect((300, 300), (1920, 1080), CRT["available"]),
                         (2560, 0))

    def test_center_in_rect(self):
        self.assertEqual(ws.center_in_rect(SIZE, HD["available"]), (920, 460))

    def test_center_never_negative(self):
        self.assertEqual(ws.center_in_rect((1920, 1080), (0, 0, 720, 480)), (0, 0))


class PickTests(unittest.TestCase):
    def test_first_run_centers_on_the_primary_screen(self):
        self.assertEqual(ws.pick_position({}, SCREENS, SIZE), (920, 460))

    def test_remembered_screen_is_used(self):
        saved = {"screen": HD["name"], "x": 2600, "y": 300}
        self.assertEqual(ws.pick_position(saved, SCREENS, SIZE), (1840, 300))

    def test_remembered_spot_on_the_crt_is_kept(self):
        # The tube is exactly 720x480, so (2560, 0) is the only legal spot there:
        # anything else must snap onto it instead of opening half off the tube.
        saved = {"screen": CRT["name"], "x": 2600, "y": 5}
        self.assertEqual(ws.pick_position(saved, SCREENS, SIZE), (2560, 0))

    def test_remembered_position_is_clamped_to_that_screen(self):
        # 2560-wide desktop later dropped to 1920: the spot must stay visible
        saved = {"screen": HD["name"], "x": 2400, "y": 1300}
        self.assertEqual(ws.pick_position(saved, SCREENS, SIZE), (1840, 920))

    def test_missing_screen_falls_back_to_primary(self):
        saved = {"screen": "\\\\.\\DISPLAY9", "x": 2600, "y": 0}   # CRT unplugged
        self.assertEqual(ws.pick_position(saved, [HD], SIZE), (1840, 0))

    def test_corrupt_coordinates_fall_back_to_centering(self):
        self.assertEqual(ws.pick_position({"x": "left", "y": None}, SCREENS, SIZE),
                         (920, 460))

    def test_no_screens_at_all_does_not_crash(self):
        self.assertEqual(ws.pick_position({}, [], SIZE), (0, 0))


class VisibleTests(unittest.TestCase):
    def test_on_screen(self):
        self.assertTrue(ws.is_on_any_screen((100, 100), SIZE, SCREENS))

    def test_mostly_off_screen_is_false(self):
        self.assertFalse(ws.is_on_any_screen((-700, 100), SIZE, SCREENS))
        self.assertFalse(ws.is_on_any_screen((100, 1500), SIZE, SCREENS))

    def test_straddling_two_screens_is_visible(self):
        self.assertTrue(ws.is_on_any_screen((2500, 0), SIZE, SCREENS))


class PersistenceTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window_state.json"
            self.assertEqual(ws.load(path), {})          # first run
            ws.save(path, HD["name"], 1640, 700)
            data = ws.load(path)
            self.assertEqual(data["screen"], HD["name"])
            self.assertEqual((data["x"], data["y"]), (1640, 700))
            self.assertEqual(ws.pick_position(data, SCREENS, SIZE), (1640, 700))

    def test_corrupt_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window_state.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(ws.load(path), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
