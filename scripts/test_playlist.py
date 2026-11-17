"""test_playlist.py — regression tests for commercial injection (no Qt, no VLC).

Run:  python scripts/test_playlist.py

Covers the two bugs that made channels look commercial-free:
  * a queue that never broke before looping (last video -> first video)
  * a channel with a single long video, which never reached "between videos"
"""

from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.catalog import Channel, VideoItem            # noqa: E402
from scripts.playlist import (                             # noqa: E402
    build_ad_break, build_playlist, ad_break_count, next_break_position,
)


def make_channel(n_videos: int, n_ads: int) -> Channel:
    return Channel(
        id="test", number=1, name="TEST", abbrev="TST",
        videos=[VideoItem(id=f"v{i}", title=f"Ep {i}", src=f"v{i}.mp4", duration=600)
                for i in range(n_videos)],
        commercials=[VideoItem(id=f"a{i}", title=f"Ad {i}", src=f"a{i}.mp4", duration=30)
                     for i in range(n_ads)],
    )


class PlaylistTests(unittest.TestCase):
    def test_breaks_between_videos(self):
        ch = make_channel(4, 10)
        q = build_playlist(ch, 1, 2, rng=random.Random(3))
        self.assertEqual(sum(1 for i in q if i.kind == "main"), 4)
        self.assertEqual(ad_break_count(q), 3)      # between the 4 videos only
        self.assertEqual(q[-1].kind, "main")        # nothing after the last one

    def test_insert_after_last_breaks_before_looping(self):
        """The last video must be followed by a break, otherwise the loop point
        (last -> first) plays with no commercial — the reported bug."""
        ch = make_channel(3, 10)
        q = build_playlist(ch, 1, 2, rng=random.Random(3), insert_after_last=True)
        self.assertEqual(ad_break_count(q), 3)
        self.assertEqual(q[-1].kind, "ad")
        self.assertEqual(sum(1 for i in q if i.kind == "ad"), sum(
            1 for i in q if i.kind == "ad"))        # sanity
        # every main video is followed by at least one ad
        kinds = [i.kind for i in q]
        for idx, kind in enumerate(kinds):
            if kind == "main":
                self.assertLess(idx + 1, len(kinds))
                self.assertEqual(kinds[idx + 1], "ad")

    def test_single_video_channel_gets_ads(self):
        """MTV has exactly one 4-hour video: without insert_after_last it had a
        queue of one item and never played a single commercial."""
        ch = make_channel(1, 51)
        plain = build_playlist(ch, 1, 2, rng=random.Random(1))
        self.assertEqual([i.kind for i in plain], ["main"])

        fixed = build_playlist(ch, 1, 2, rng=random.Random(1), insert_after_last=True)
        self.assertEqual(fixed[0].kind, "main")
        self.assertGreaterEqual(len(fixed), 2)
        self.assertTrue(all(i.kind == "ad" for i in fixed[1:]))

    def test_ads_come_from_own_channel_pool(self):
        ch = make_channel(2, 5)
        ch.commercials = [VideoItem(id="jp1", title="JP ad", src="jp1.mp4")]
        q = build_playlist(ch, 2, 2, rng=random.Random(0), insert_after_last=True)
        for item in q:
            if item.kind == "ad":
                self.assertEqual(item.video.id, "jp1")

    def test_no_pool_no_ads(self):
        ch = make_channel(3, 0)
        q = build_playlist(ch, 1, 2, insert_after_last=True)
        self.assertTrue(all(i.kind == "main" for i in q))

    def test_min_ads_validation(self):
        ch = make_channel(2, 3)
        with self.assertRaises(ValueError):
            build_playlist(ch, 3, 1)
        with self.assertRaises(ValueError):
            build_playlist(ch, -1, 1)

    # ── standalone break (mid-roll) ──────────────────────────────────────
    def test_ad_break_size_and_pool(self):
        ch = make_channel(1, 10)
        for seed in range(20):
            br = build_ad_break(ch, 1, 2, rng=random.Random(seed))
            self.assertIn(len(br), (1, 2))
            self.assertTrue(all(i.kind == "ad" for i in br))
            ids = [i.video.id for i in br]
            self.assertEqual(len(ids), len(set(ids)))     # no repeat inside a break

    def test_ad_break_without_pool(self):
        ch = make_channel(1, 0)
        self.assertEqual(build_ad_break(ch, 1, 2), [])

    # ── v0.6.4: 5-10 ads per break ─────────────────────────────────────────

    def test_big_breaks_with_enough_ads(self):
        ch = make_channel(1, 12)
        for seed in range(50):
            br = build_ad_break(ch, 5, 10, rng=random.Random(seed))
            self.assertTrue(5 <= len(br) <= 10)
            ids = [i.video.id for i in br]
            self.assertEqual(len(ids), len(set(ids)))

    def test_big_breaks_with_small_pool_degrade_gracefully(self):
        ch = make_channel(1, 3)                       # fewer ads than the minimum
        br = build_ad_break(ch, 5, 10, rng=random.Random(1))
        self.assertEqual(len(br), 3)                  # whole pool, each once
        self.assertEqual(len({i.video.id for i in br}), 3)

    def test_break_does_not_open_with_previous_closer(self):
        ch = make_channel(1, 8)
        for seed in range(200):
            for prev in ("a0", "a3", "a7"):
                br = build_ad_break(ch, 5, 10, rng=random.Random(seed), avoid_first_id=prev)
                self.assertNotEqual(br[0].video.id, prev)
                self.assertEqual(len({i.video.id for i in br}), len(br))

    def test_avoid_first_is_ignored_for_single_ad_pool(self):
        ch = make_channel(1, 1)
        br = build_ad_break(ch, 5, 10, avoid_first_id="a0")
        self.assertEqual([i.video.id for i in br], ["a0"])     # nothing else to play

    def test_between_video_breaks_use_the_same_range(self):
        ch = make_channel(4, 12)
        q = build_playlist(ch, 5, 10, rng=random.Random(5), insert_after_last=True)
        run = 0
        runs = []
        for it in q:
            if it.kind == "ad":
                run += 1
            elif run:
                runs.append(run); run = 0
        if run:
            runs.append(run)
        self.assertEqual(len(runs), 4)
        self.assertTrue(all(5 <= r <= 10 for r in runs), runs)

    def test_breaks_sit_at_fixed_points_in_the_show(self):
        E = 600.0
        self.assertEqual(next_break_position(0, E), 600)        # joined at the start
        self.assertEqual(next_break_position(100, E), 600)
        self.assertEqual(next_break_position(1530, E), 1800)    # joined at 25:30 -> break at 30:00
        self.assertEqual(next_break_position(600.4, E), 1200)   # just resumed from the 10:00 break
        self.assertEqual(next_break_position(1199.9, E), 1800)  # <60 s away -> skip one
        self.assertEqual(next_break_position(540, E), 600)      # exactly 60 s away: kept
        self.assertEqual(next_break_position(540.5, E), 1200)   # 59.5 s away: skipped

    def test_break_position_disabled(self):
        self.assertEqual(next_break_position(123, 0), 0.0)
        self.assertEqual(next_break_position(123, -5), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
