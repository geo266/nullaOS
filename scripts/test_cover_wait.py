"""test_cover_wait.py — regression tests for the tuning/resume cover.

Run:  python scripts/test_cover_wait.py

The bug these pin down (v0.6.5, Kawaii TV): the snow lifted as soon as VLC's
clock reported the target time, or after a flat 3.5 s, while the video output
still held the previous picture — so one frame of the old clip sat on screen
for about a second before the episode started.  The cover must now stay up
until the clock is at the target AND still moving, and must never stay up
forever.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.cover_wait import CoverWait, WAIT, RELEASE, GIVE_UP   # noqa: E402

POLL = 0.1          # app.py polls every 100 ms
TARGET = 1500.0     # a join 25 minutes into a 44-minute episode


def run(cw: CoverWait, positions, loaded=True, start=0.0):
    """Feed one poll per entry; return [(elapsed, action)] for the interesting ones."""
    out = []
    now = start
    for pos in positions:
        out.append((round(now, 2), cw.update(now, pos, loaded)))
        now += POLL
    return out


def first_action(events, action):
    for t, a in events:
        if a == action:
            return t
    return None


class ReleaseTests(unittest.TestCase):
    def test_normal_file_releases_once_the_clock_moves(self):
        cw = CoverWait(TARGET)
        events = run(cw, [0.0, 0.2, 1500.2, 1500.4, 1500.6])
        self.assertEqual(events[2][1], WAIT)          # saw the target, not proven yet
        self.assertEqual(events[3][1], WAIT)          # one advancing poll
        self.assertEqual(events[4][1], RELEASE)       # two advancing polls

    def test_no_release_before_the_seek_lands(self):
        """The Kawaii case: six seconds of seeking is not a licence to show a
        stale frame."""
        cw = CoverWait(TARGET)
        events = run(cw, [0.3] * 60 + [1500.1, 1500.3, 1500.5])
        self.assertIsNone(first_action(events[:-3], RELEASE))
        self.assertEqual(events[-1][1], RELEASE)

    def test_frozen_picture_is_never_released_as_success(self):
        """A vout stuck on the old frame reports the new time but does not
        advance — that must not count as a landed seek."""
        cw = CoverWait(TARGET, stall_s=1.5)
        events = run(cw, [1500.0] * 40)
        self.assertIsNone(first_action(events, RELEASE))
        self.assertEqual(events[-1][1], GIVE_UP)
        self.assertGreaterEqual(first_action(events, GIVE_UP), 1.5)

    def test_join_at_zero_releases_after_the_media_plays(self):
        cw = CoverWait(0.0, first_frame_s=0.35)
        events = run(cw, [0.0, 0.0, 0.4, 0.5, 0.6])
        self.assertEqual(events[2][1], WAIT)          # first frame seen
        self.assertEqual(events[4][1], RELEASE)

    def test_join_at_zero_does_not_release_while_still_at_zero(self):
        cw = CoverWait(0.0)
        events = run(cw, [0.0] * 30)
        self.assertIsNone(first_action(events, RELEASE))

    def test_hard_deadline(self):
        cw = CoverWait(TARGET, deadline_s=12.0)
        events = run(cw, [0.0] * 140)
        self.assertIsNone(first_action(events, RELEASE))
        gave_up = first_action(events, GIVE_UP)
        self.assertIsNotNone(gave_up)
        self.assertGreater(gave_up, 11.9)
        self.assertLess(gave_up, 12.3)


class ToleranceTests(unittest.TestCase):
    def test_early_tolerance_is_tight(self):
        cw = CoverWait(TARGET)
        cw.update(0.0, 1490.0, True)                 # 10 s early: too far
        self.assertFalse(cw.landed)
        cw.update(0.1, 1497.0, True)                 # 3 s early: close enough
        self.assertTrue(cw.landed)

    def test_late_tolerance_widens_after_landing(self):
        cw = CoverWait(TARGET)
        cw.update(0.0, 1500.0, True)                 # landed
        cw.update(0.1, 1500.1, True)
        self.assertEqual(cw.update(0.2, 1508.0, True), RELEASE)

    def test_not_loaded_never_lands(self):
        cw = CoverWait(TARGET)
        events = run(cw, [1500.0] * 5, loaded=False)
        self.assertTrue(all(a == WAIT for _, a in events))
        self.assertFalse(cw.landed)


class RecoveryTests(unittest.TestCase):
    def test_corrective_seek_starts_the_confirmation_again(self):
        cw = CoverWait(TARGET)
        self.assertEqual(cw.update(0.0, 1498.0, True), WAIT)
        self.assertEqual(cw.update(0.1, 1200.0, True), WAIT)   # moved away
        self.assertFalse(cw.landed)
        self.assertEqual(cw.update(0.2, 1500.1, True), WAIT)   # back on target
        self.assertTrue(cw.landed)

    def test_release_needs_several_polls_even_if_position_is_perfect(self):
        cw = CoverWait(TARGET)
        self.assertEqual(cw.update(0.0, TARGET, True), WAIT)
        self.assertEqual(cw.confirmations, 0)

    def test_elapsed_is_measured_from_the_first_poll(self):
        cw = CoverWait(TARGET)
        cw.update(100.0, 0.0, True)
        self.assertAlmostEqual(cw.elapsed(105.0), 5.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
