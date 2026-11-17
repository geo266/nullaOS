"""test_timeline.py — the broadcast timeline (programmes + ad pods), no Qt.

Run:  python scripts/test_timeline.py

These pin the behaviour the guide and the player now depend on:
  * segments tile the wall clock with no gaps and no overlaps,
  * a long programme breaks every N minutes but never near its end,
  * a short programme does not break inside itself,
  * the same catalog always produces the same ads (deterministic),
  * two channels do not break at the same moment,
  * the guide's programme blocks are contiguous and include the ad time.
"""

from __future__ import annotations

import os
import sys
import datetime
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.catalog import Channel, VideoItem                    # noqa: E402
from scripts.timeline import (                                     # noqa: E402
    AdPolicy, ChannelTimeline, DEFAULT_AD_S, policy_for_channel,
)

MIN = 60.0
ORIGIN = 1_700_000_000.0          # arbitrary fixed epoch


def V(name: str, seconds: float) -> VideoItem:
    return VideoItem(id=name, title=name, src=f"{name}.mp4", duration=seconds)


def make_channel(n_videos=2, video_len=44 * MIN + 40, n_ads=12, ad_len=30,
                 cid="kawaii-tv") -> Channel:
    return Channel(
        id=cid, number=1, name=cid.upper(), abbrev="KAW",
        videos=[V(f"ep{i}", video_len) for i in range(n_videos)],
        commercials=[V(f"ad{i}", ad_len) for i in range(n_ads)],
    )


def duration_of(v: VideoItem) -> float:
    return v.duration


POLICY = AdPolicy(every_s=10 * MIN, min_ads=5, max_ads=10,
                  min_video_s=20 * MIN, tail_guard_s=90)


class TilingTests(unittest.TestCase):
    def setUp(self):
        self.tl = ChannelTimeline(make_channel(), duration_of, POLICY, ORIGIN)

    def test_cycle_has_content(self):
        self.assertGreater(self.tl.cycle_length, 0)

    def test_segments_tile_without_gaps(self):
        airings = self.tl.airings(ORIGIN, ORIGIN + 8 * 3600, limit=2000)
        self.assertGreater(len(airings), 10)
        for a, b in zip(airings, airings[1:]):
            self.assertAlmostEqual(a.end, b.start, places=6)
            self.assertGreater(a.length, 0)

    def test_airing_at_round_trips(self):
        for hours in (0, 3, 17, 40, 71):
            t = ORIGIN + hours * 3600 + 17
            a = self.tl.airing_at(t)
            self.assertIsNotNone(a)
            self.assertLessEqual(a.start, t)
            self.assertGreaterEqual(a.end, t)
            self.assertEqual(a.video.id, self.tl.airing_at(a.start + 0.01).video.id)

    def test_negative_time_is_handled(self):
        a = self.tl.airing_at(ORIGIN - 5000)
        self.assertIsNotNone(a)
        self.assertLessEqual(a.start, ORIGIN - 5000)
        self.assertGreaterEqual(a.end, ORIGIN - 5000)

    def test_next_after(self):
        a = self.tl.airing_at(ORIGIN + 100)
        b = self.tl.next_after(a)
        self.assertAlmostEqual(a.end, b.start, places=6)


class BreakTests(unittest.TestCase):
    def test_long_programme_breaks_every_ten_minutes(self):
        tl = ChannelTimeline(make_channel(n_videos=1, video_len=44 * MIN), duration_of,
                             POLICY, ORIGIN)
        airings = tl.airings(ORIGIN, ORIGIN + 3 * 3600, limit=500)
        main = [a for a in airings if a.kind == "main"][:5]
        # 44 min, breaks at 10/20/30/40 -> five programme segments of 10/10/10/10/4 min
        self.assertEqual(len(main), 5)
        self.assertAlmostEqual(main[0].length, 10 * MIN, delta=0.5)
        self.assertAlmostEqual(main[1].length, 10 * MIN, delta=0.5)
        self.assertAlmostEqual(main[4].length, 4 * MIN, delta=0.5)

    def test_no_break_near_the_end(self):
        tl = ChannelTimeline(make_channel(n_videos=1, video_len=41 * MIN), duration_of,
                             POLICY, ORIGIN)
        airings = tl.airings(ORIGIN, ORIGIN + 41 * MIN, limit=500)
        main = [a for a in airings if a.kind == "main"]
        self.assertGreaterEqual(main[-1].length, 90.0)

    def test_short_programme_does_not_break_inside(self):
        tl = ChannelTimeline(make_channel(n_videos=1, video_len=15 * MIN), duration_of,
                             POLICY, ORIGIN)
        airings = tl.airings(ORIGIN, ORIGIN + 15 * MIN, limit=100)
        self.assertEqual([a.kind for a in airings], ["main"])

    def test_pods_are_between_programmes_even_for_short_items(self):
        tl = ChannelTimeline(make_channel(n_videos=2, video_len=5 * MIN), duration_of,
                             POLICY, ORIGIN)
        airings = tl.airings(ORIGIN, ORIGIN + 12 * MIN, limit=100)
        self.assertEqual(airings[0].kind, "main")
        self.assertEqual(airings[1].kind, "ad")

    def test_pod_size_respects_policy(self):
        tl = ChannelTimeline(make_channel(), duration_of, POLICY, ORIGIN)
        airings = tl.airings(ORIGIN, ORIGIN + 2 * 3600, limit=400)
        pods = {}
        for a in airings:
            if a.kind == "ad":
                pods.setdefault((a.programme_index, a.pod_index), a.pod_len)
        self.assertTrue(pods)
        for n in pods.values():
            self.assertGreaterEqual(n, POLICY.min_ads)
            self.assertLessEqual(n, POLICY.max_ads)

    def test_no_ads_policy(self):
        tl = ChannelTimeline(make_channel(), duration_of,
                             AdPolicy(every_s=0, min_ads=0, max_ads=0), ORIGIN)
        airings = tl.airings(ORIGIN, ORIGIN + 3 * 3600, limit=200)
        self.assertTrue(all(a.kind == "main" for a in airings))


class DeterminismTests(unittest.TestCase):
    def test_same_catalog_same_ads(self):
        a = ChannelTimeline(make_channel(), duration_of, POLICY, ORIGIN)
        b = ChannelTimeline(make_channel(), duration_of, POLICY, ORIGIN)
        self.assertEqual(a.cycle_length, b.cycle_length)
        for x, y in zip(a.airings(ORIGIN, ORIGIN + 4 * 3600, limit=600),
                        b.airings(ORIGIN, ORIGIN + 4 * 3600, limit=600)):
            self.assertEqual((x.video.id, x.start), (y.video.id, y.start))

    def test_different_channels_break_at_different_times(self):
        a = ChannelTimeline(make_channel(cid="kawaii-tv"), duration_of, POLICY, ORIGIN)
        b = ChannelTimeline(make_channel(cid="drama_tv"), duration_of, POLICY, ORIGIN)
        # same content, different channel -> different ad choices, hence offset
        self.assertNotEqual(a.cycle_length, b.cycle_length)

    def test_origin_phase_shifts_the_schedule(self):
        a = ChannelTimeline(make_channel(), duration_of, POLICY, ORIGIN)
        b = ChannelTimeline(make_channel(), duration_of, POLICY, ORIGIN + 17 * MIN)
        self.assertNotEqual(a.airing_at(ORIGIN + 123).video.id,
                            b.airing_at(ORIGIN + 123).video.id)


class BlockTests(unittest.TestCase):
    def test_blocks_are_contiguous_and_include_ads(self):
        tl = ChannelTimeline(make_channel(), duration_of, POLICY, ORIGIN)
        blocks = tl.programme_blocks(ORIGIN + 100, ORIGIN + 6 * 3600, limit=40)
        self.assertGreater(len(blocks), 2)
        for a, b in zip(blocks, blocks[1:]):
            self.assertAlmostEqual(a.end, b.start, places=6)
        # a block is longer than the programme itself: the pods are inside it
        self.assertGreater(blocks[0].length, 44 * MIN)

    def test_blocks_start_before_the_window_when_it_begins_mid_programme(self):
        tl = ChannelTimeline(make_channel(), duration_of, POLICY, ORIGIN)
        t0 = ORIGIN + 25 * MIN          # inside the first programme
        blocks = tl.programme_blocks(t0, t0 + 3600, limit=20)
        self.assertLessEqual(blocks[0].start, t0)

    def test_blocks_fill_the_window_for_short_programmes(self):
        """Regression: a fixed scan-back plus a block cap used to truncate the
        list before the window (the guide drew two cells and then nothing)."""
        tl = ChannelTimeline(make_channel(n_videos=3, video_len=5 * MIN,
                                          n_ads=6, ad_len=20),
                             duration_of, POLICY, ORIGIN)
        t0 = ORIGIN + 6 * 3600         # far from the cycle origin
        blocks = tl.programme_blocks(t0, t0 + 7200)
        self.assertGreaterEqual(len(blocks), 8)
        self.assertGreaterEqual(blocks[-1].end, t0 + 7200 - 60)
        for a, b in zip(blocks, blocks[1:]):
            self.assertAlmostEqual(a.end, b.start, places=6)
            self.assertGreater(b.start, t0 - 3600)


class DurationTests(unittest.TestCase):
    def test_unknown_lengths_use_defaults(self):
        ch = Channel(id="unknown", number=1, name="U", abbrev="U",
                     videos=[VideoItem(id="v", title="v", src="v.mp4", duration=0)],
                     commercials=[VideoItem(id="a", title="a", src="a.mp4", duration=0)])
        tl = ChannelTimeline(ch, lambda v: 0.0, POLICY, ORIGIN)
        airings = tl.airings(ORIGIN, ORIGIN + 3600, limit=50)
        # 30-minute default programme, so the first mid-roll splits it at 10 min
        self.assertEqual(airings[0].kind, "main")
        self.assertEqual(airings[0].length, 10 * MIN)
        self.assertEqual(airings[1].kind, "ad")
        self.assertEqual(airings[1].length, float(DEFAULT_AD_S))

    def test_rebuild_when_a_length_is_learned(self):
        lengths = {"ep0": 44 * MIN, "ep1": 44 * MIN}
        ch = make_channel(n_videos=2)
        tl = ChannelTimeline(ch, lambda v: lengths.get(v.id, v.duration), POLICY, ORIGIN)
        before = tl.cycle_length
        lengths["ep0"] = 20 * MIN
        self.assertTrue(tl.rebuild_if_changed())
        self.assertNotEqual(before, tl.cycle_length)
        self.assertFalse(tl.rebuild_if_changed())

    def test_empty_channel(self):
        ch = Channel(id="empty", number=1, name="E", abbrev="E")
        tl = ChannelTimeline(ch, duration_of, POLICY, ORIGIN)
        self.assertIsNone(tl.airing_at(ORIGIN))
        self.assertEqual(tl.airings(ORIGIN, ORIGIN + 100), [])


class PolicyTests(unittest.TestCase):
    def test_base_policy_is_used_without_jitter(self):
        p = policy_for_channel(make_channel(), POLICY, jitter_s=0)
        self.assertEqual(p.every_s, 600)
        self.assertEqual((p.min_ads, p.max_ads), (5, 10))

    def test_jitter_differs_per_channel_and_stays_close(self):
        a = policy_for_channel(make_channel(cid="kawaii-tv"), POLICY, jitter_s=120)
        b = policy_for_channel(make_channel(cid="drama_tv"), POLICY, jitter_s=120)
        self.assertNotEqual(a.every_s, b.every_s)
        for p in (a, b):
            self.assertGreaterEqual(p.every_s, 480)
            self.assertLessEqual(p.every_s, 720)

    def test_channel_json_override_wins(self):
        ch = make_channel()
        ch.ad_every_min, ch.ad_min, ch.ad_max = 7, 2, 3
        p = policy_for_channel(ch, POLICY, jitter_s=120)
        self.assertEqual(p.every_s, 420)
        self.assertEqual((p.min_ads, p.max_ads), (2, 3))

    def test_negative_override_disables_midrolls(self):
        ch = make_channel()
        ch.ad_every_min = -1
        p = policy_for_channel(ch, POLICY, jitter_s=120)
        self.assertEqual(p.every_s, 0)


class OffsetTests(unittest.TestCase):
    def test_midroll_segments_carry_the_file_offset(self):
        tl = ChannelTimeline(make_channel(n_videos=1, video_len=44 * MIN), duration_of,
                             POLICY, ORIGIN)
        mains = [a for a in tl.airings(ORIGIN, ORIGIN + 3 * 3600, limit=500)
                 if a.kind == "main"][:5]
        self.assertEqual(mains[0].video_offset, 0)
        self.assertAlmostEqual(mains[1].video_offset, 10 * MIN, delta=0.5)
        t = mains[1].start + 5
        self.assertAlmostEqual(mains[1].position_at(t), 10 * MIN + 5, delta=0.5)

    def test_ads_start_at_zero(self):
        tl = ChannelTimeline(make_channel(), duration_of, POLICY, ORIGIN)
        ads = [a for a in tl.airings(ORIGIN, ORIGIN + 3 * 3600, limit=500) if a.kind == "ad"]
        self.assertTrue(ads)
        self.assertTrue(all(a.video_offset == 0 for a in ads))


class DaypartTests(unittest.TestCase):
    def _channel(self):
        ch = make_channel(n_videos=2, video_len=30 * MIN, n_ads=6, ad_len=30)
        ch.videos.append(VideoItem(id="morning_show", title="Morning Show",
                                   src="m.mp4", duration=30 * MIN, daypart="morning"))
        ch.videos.append(VideoItem(id="late_show", title="Late Show",
                                   src="l.mp4", duration=30 * MIN, daypart="late_night"))
        ch.commercials.append(VideoItem(id="xmas_ad", title="Xmas Ad", src="x.mp4",
                                        duration=30, season="christmas"))
        return ch

    def _timeline(self, dayparts=None):
        ch = self._channel()
        dp = dayparts or {"morning": (5, 11), "late_night": (23, 5)}
        return ChannelTimeline(ch, duration_of, POLICY, ORIGIN, dayparts=dp), ch

    def test_windows_tile_the_day(self):
        from scripts.timeline import build_windows
        wins = build_windows({"morning": (5, 11), "late_night": (23, 5)})
        self.assertEqual(wins[0], ("late_night", 0, 5))
        self.assertEqual(wins[1], ("morning", 5, 11))
        self.assertEqual(wins[-1], ("late_night", 23, 24))
        hours = [h for _, s, e in wins for h in range(s, e)]
        self.assertEqual(hours, list(range(24)))

    def test_morning_window_starts_with_a_morning_programme(self):
        tl, _ch = self._timeline()
        day = datetime.datetime.now().replace(hour=0, minute=0, second=0,
                                              microsecond=0).timestamp()
        air = tl.airing_at(day + 7 * 3600 + 30)
        self.assertIsNotNone(air)
        self.assertEqual(air.video.daypart, "morning", air.video.title)

    def test_late_night_window_uses_its_own_programme(self):
        tl, _ch = self._timeline()
        day = datetime.datetime.now().replace(hour=0, minute=0, second=0,
                                              microsecond=0).timestamp()
        air = tl.airing_at(day + 23 * 3600 + 60)
        self.assertEqual(air.video.daypart, "late_night", air.video.title)

    def test_afternoon_is_the_main_rotation(self):
        tl, _ch = self._timeline()
        day = datetime.datetime.now().replace(hour=0, minute=0, second=0,
                                              microsecond=0).timestamp()
        air = tl.airing_at(day + 14 * 3600)
        self.assertEqual(air.video.daypart, "", air.video.title)

    def test_a_programme_never_runs_past_its_window(self):
        tl, _ch = self._timeline()
        day = datetime.datetime.now().replace(hour=0, minute=0, second=0,
                                              microsecond=0).timestamp()
        for t in (day + 10 * 3600 + 3590, day + 4 * 3600 + 3590):
            air = tl.airing_at(t)
            self.assertLessEqual(air.end - t, 61, air.video.title)
            end = datetime.datetime.fromtimestamp(air.end)
            self.assertIn(end.hour, (5, 11), end.strftime("%H:%M:%S"))

    def test_airings_cross_the_window_boundary(self):
        tl, _ch = self._timeline()
        day = datetime.datetime.now().replace(hour=0, minute=0, second=0,
                                              microsecond=0).timestamp()
        airings = tl.airings(day + 10 * 3600, day + 12 * 3600, limit=200)
        self.assertTrue(airings)
        for a, b in zip(airings, airings[1:]):
            self.assertAlmostEqual(a.end, b.start, places=6)

    def test_seasonal_ads_only_appear_in_season(self):
        from scripts.catalog import season_active
        self.assertTrue(season_active("christmas", datetime.datetime(2026, 12, 20)))
        self.assertFalse(season_active("christmas", datetime.datetime(2026, 7, 1)))
        self.assertTrue(season_active("christmas", datetime.datetime(2027, 1, 3)))
        self.assertFalse(season_active("christmas", datetime.datetime(2027, 1, 9)))

    def test_ad_pool_respects_season_and_daypart(self):
        tl, ch = self._timeline()
        xmas = [a for a in ch.commercials if a.id == "xmas_ad"]
        self.assertTrue(xmas)
        dec = tl._ad_pool("main", datetime.datetime(2026, 12, 20, 14, 0))
        jul = tl._ad_pool("main", datetime.datetime(2026, 7, 1, 14, 0))
        self.assertIn(xmas[0], dec)
        self.assertNotIn(xmas[0], jul)
        night = tl._ad_pool("late_night", datetime.datetime(2026, 7, 1, 1, 0))
        self.assertTrue(all(not a.daypart or a.daypart == "late_night" for a in night))


class FolderTagTests(unittest.TestCase):
    def test_folders_tag_programmes_and_ads(self):
        import tempfile
        from pathlib import Path
        from scripts.catalog import scan_real_folder
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ch = root / "Test TV"
            (ch / "Morning").mkdir(parents=True)
            (ch / "Late Night").mkdir()
            (ch / "Commercials" / "Christmas").mkdir(parents=True)
            (ch / "Commercials" / "Late Night").mkdir()
            for p in (ch / "plain.mp4", ch / "Morning" / "am.mp4",
                      ch / "Late Night" / "pm.mp4",
                      ch / "Commercials" / "ad.mp4",
                      ch / "Commercials" / "Christmas" / "xmas.mp4",
                      ch / "Commercials" / "Late Night" / "latead.mp4"):
                p.write_bytes(b"\x00")
            cat = scan_real_folder(root)
            c = cat.channels[0]
            by_id = {v.id: v for v in c.videos + c.commercials}
            self.assertEqual(by_id["am"].daypart, "morning")
            self.assertEqual(by_id["pm"].daypart, "late_night")
            self.assertEqual(by_id["xmas"].season, "christmas")
            self.assertEqual(by_id["latead"].daypart, "late_night")
            self.assertEqual(by_id["ad"].daypart, "")
            self.assertEqual(by_id["ad"].season, "")
            self.assertEqual(by_id["plain"].daypart, "")
            self.assertIn(by_id["xmas"], c.commercials)
            self.assertIn(by_id["am"], c.videos)


class LateJumpTests(unittest.TestCase):
    def _tl(self):
        return ChannelTimeline(make_channel(n_videos=1, video_len=5 * MIN,
                                            n_ads=6, ad_len=20),
                               duration_of, POLICY, ORIGIN)

    def test_walks_forward_when_several_segments_are_over(self):
        tl = self._tl()
        first = tl.airing_at(ORIGIN)
        later = ORIGIN + 40 * MIN
        nxt = tl.airing_at_or_after(later, tl.next_after(first))
        self.assertIsNotNone(nxt)
        self.assertLessEqual(nxt.start, later)
        self.assertGreater(nxt.end, later)

    def test_keeps_the_current_airing_when_not_late(self):
        tl = self._tl()
        a = tl.airing_at(ORIGIN)
        got = tl.airing_at_or_after(ORIGIN + 1, a)
        self.assertEqual(got.segment_index, a.segment_index)

    def test_never_returns_an_airing_that_already_ended(self):
        tl = self._tl()
        first = tl.airing_at(ORIGIN)
        t = first.end + 1
        got = tl.airing_at_or_after(t, first)
        self.assertGreater(got.end, t)


class BoundaryTests(unittest.TestCase):
    """v0.7.7: transitions sit exactly on segment boundaries, and a rounding
    error there used to re-select the segment that had just ended — the
    “Join 30s is past the end (30s)” clamp and the one-second ad blinks."""

    def _timeline(self):
        ads = [VideoItem(id=f"a{i}", title=f"a{i}", src=f"a{i}.mp4", duration=d)
               for i, d in enumerate((1, 2, 3, 7, 13, 15, 20, 30, 11, 9, 6, 4))]
        ch = Channel(id="edge", number=1, name="EDGE", abbrev="EDG",
                     videos=[VideoItem(id="p", title="p", src="p.mp4", duration=600)],
                     commercials=ads)
        return ChannelTimeline(ch, duration_of, AdPolicy(0, 5, 8, 1200, 90), ORIGIN)

    def test_next_after_always_moves_forward(self):
        tl = self._timeline()
        for a in tl.airings(ORIGIN, ORIGIN + 3600, limit=800):
            nxt = tl.next_after(a)
            self.assertIsNotNone(nxt)
            self.assertGreater(nxt.start, a.start + 0.001,
                               f"{a.video.id} {a.start}-{a.end}")

    def test_a_tick_on_the_boundary_lands_in_the_next_slot(self):
        tl = self._timeline()
        for a in tl.airings(ORIGIN, ORIGIN + 3600, limit=800):
            now = a.end - 0.25                      # the 1 s tick fires early
            nxt = tl.airing_at_or_after(now, tl.next_after(a))
            self.assertGreater(nxt.end, now)
            # Same rule the app uses: never start with less than half of a very
            # short slot (or 2 s of a normal one) left.
            limit = min(2.0, max(0.4, nxt.length * 0.5))
            self.assertLess(nxt.position_at(now), nxt.length - limit + 0.001,
                            f"join {nxt.position_at(now):.1f}s of {nxt.length:.1f}s")

    def test_never_joins_an_airing_that_already_ended(self):
        tl = self._timeline()
        for a in tl.airings(ORIGIN, ORIGIN + 3600, limit=800):
            for slack in (0.0, 0.01, 5.0, 30.0):
                now = a.end + slack
                nxt = tl.airing_at_or_after(now, tl.next_after(a))
                self.assertGreater(nxt.end, now, f"slack {slack}")


class TickLoopTests(unittest.TestCase):
    """v0.7.7: simulate the 1 s timeline tick over two hours.

    The tick used to be suppressed while a seek settled, so it ran 1–2 s late and
    every join was further into its slot; after a pod of short ads the player was
    joining them at their last second (a one-second blink).  With the tick on
    time, the join offset must stay bounded no matter how many transitions pass.
    """

    def test_join_offset_stays_bounded(self):
        ads = [VideoItem(id=f"a{i}", title=f"a{i}", src=f"a{i}.mp4", duration=d)
               for i, d in enumerate((10, 12, 15, 20, 30, 15, 30, 10, 25, 15, 30, 12))]
        ch = Channel(id="loop", number=1, name="LOOP", abbrev="LOP",
                     videos=[VideoItem(id="p", title="p", src="p.mp4", duration=600)],
                     commercials=ads)
        tl = ChannelTimeline(ch, duration_of, AdPolicy(0, 5, 8, 1200, 90), ORIGIN)

        now = ORIGIN
        air = tl.airing_at(now)
        worst = 0.0
        for step in range(2400):                 # 40 min at a 1 s tick
            now += 1.0
            if now < air.end - 0.25:
                continue
            nxt = tl.airing_at_or_after(now, tl.next_after(air))
            limit = min(2.0, max(0.4, nxt.length * 0.5))
            if nxt.position_at(now) > nxt.length - limit:
                nxt = tl.airing_at_or_after(now, tl.next_after(nxt))
            air = nxt
            offset = air.position_at(now)
            worst = max(worst, offset)
            self.assertLess(offset, air.length, f"step {step} {air.video.id}")
        self.assertLess(worst, 3.0, f"worst join offset {worst:.2f}s")


if __name__ == "__main__":
    unittest.main(verbosity=2)
