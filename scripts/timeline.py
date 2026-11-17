"""
timeline.py — what channel C is airing at time T (programmes *and* ad pods)

Before v0.7.0 there were three different answers to that question:

  * the player kept a queue and fired mid-rolls from a 1 s timer,
  * the guide invented 9:30 / 10:00 / 10:30 labels and repeated the channel's
    videos into them,
  * the guide preview used the schedule state's content-only position.

This module is now the only answer.

Two layouts, one interface
--------------------------
**Cycle** (default) — a loop of programme segments and ad pods, anchored to the
channel's persisted `start_time`:

    prog(0..10min) pod prog(10..20min) pod … prog(tail) pod  → next video …

**Day windows** (when the channel has daypart folders, v0.7.1) — the day is cut
into windows ("main", "morning", "late_night", …).  Each window has its own
cycle built from the programmes and ads that belong to it, anchored at the
window's clock time.  A programme never runs past the end of its window.

In both layouts the ads are chosen by a seeded RNG (`channel|video|pod`), so the
same catalog produces the same schedule on every run and the guide can look days
ahead.  Ad pools are filtered by date and by window:

  * `Commercials/Christmas/…` only in season,
  * `Commercials/Late Night/…` only in the late-night window,
  * `Commercials/Morning/…` only in the morning window,
  * plain `Commercials/…` always.

Qt-free; `test_timeline.py` covers the maths.
"""

from __future__ import annotations

import bisect
import datetime
import logging
import random
import zlib
from dataclasses import dataclass, replace
from typing import Callable, Optional

from .catalog import Channel, VideoItem, season_active

log = logging.getLogger("timeline")

DEFAULT_PROGRAMME_S = 1800.0    # no length known and no name hint: 30 min
DEFAULT_AD_S = 30.0             # ditto for a commercial
MIN_SEGMENT_S = 1.0
DAY_S = 24 * 3600


@dataclass(frozen=True)
class AdPolicy:
    """How a channel breaks for commercials."""
    every_s: float = 600.0        # mid-roll every N seconds of programme
    min_ads: int = 5
    max_ads: int = 10
    min_video_s: float = 1200.0   # shorter items break only between programmes
    tail_guard_s: float = 90.0    # never break this close to the end

    def normalised(self) -> "AdPolicy":
        lo = max(0, int(self.min_ads))
        hi = max(lo, int(self.max_ads))
        return AdPolicy(
            every_s=max(0.0, float(self.every_s)),
            min_ads=lo, max_ads=hi,
            min_video_s=max(0.0, float(self.min_video_s)),
            tail_guard_s=max(0.0, float(self.tail_guard_s)),
        )


@dataclass(frozen=True)
class Airing:
    """One segment of a channel's timeline, with absolute wall-clock times."""
    kind: str                 # "main" | "ad"
    video: VideoItem
    start: float              # epoch seconds
    end: float                # epoch seconds
    programme_index: int = 0  # index of the programme in the layout
    pod_index: int = -1       # which pod of that programme (-1 = programme segment)
    ad_index: int = -1        # index inside the pod (-1 = programme)
    pod_len: int = 0          # ads in that pod
    segment_index: int = 0    # index in the layout (for change detection)
    video_offset: float = 0.0 # seconds into the file at `start`
    run: int = 0              # which pass through the programme list

    @property
    def length(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def is_ad(self) -> bool:
        return self.kind == "ad"

    def position_at(self, t: float) -> float:
        """Where to seek in the file to be live at epoch `t`."""
        return max(0.0, self.video_offset + (t - self.start))


@dataclass
class ProgrammeBlock:
    """A programme as the guide lists it: first segment start → last pod end."""
    video: VideoItem
    start: float
    end: float
    programme_index: int = 0
    run: int = 0

    @property
    def length(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class _Seg:
    kind: str
    video: VideoItem
    length: float
    programme_index: int
    pod_index: int
    ad_index: int
    pod_len: int
    video_offset: float = 0.0
    run: int = 0


# ── window layout (dayparts) ────────────────────────────────────────────────

def _hour_in(hour: int, start_h: int, end_h: int) -> bool:
    if start_h == end_h:
        return True
    if start_h < end_h:
        return start_h <= hour < end_h
    return hour >= start_h or hour < end_h


def build_windows(dayparts: dict[str, tuple[int, int]]) -> list[tuple[str, int, int]]:
    """Turn daypart ranges into a list of windows that tile 0..24.

    Gaps are filled with `main`; overlapping dayparts are resolved hour by hour
    (first match wins, in dict order).  Windows never cross midnight, which keeps
    every layout keyed to one calendar day.
    """
    names: list[str] = []
    for h in range(24):
        name = "main"
        for dp_name, (sh, eh) in dayparts.items():
            if _hour_in(h, sh, eh):
                name = dp_name
                break
        names.append(name)

    windows: list[tuple[str, int, int]] = []
    i = 0
    while i < 24:
        j = i
        while j < 24 and names[j] == names[i]:
            j += 1
        windows.append((names[i], i, j))
        i = j
    return windows


class ChannelTimeline:
    """The programmes + ad pods of one channel, in wall-clock time."""

    def __init__(self, channel: Channel, duration_of: Callable[[VideoItem], float],
                 policy: AdPolicy, origin: float = 0.0,
                 dayparts: Optional[dict[str, tuple[int, int]]] = None):
        self.channel = channel
        self._duration_of = duration_of
        self.policy = policy.normalised()
        self.origin = float(origin)
        self.dayparts = dict(dayparts or {})
        self.windows = build_windows(self.dayparts) if self.dayparts else []
        self._ad_ids = {c.id for c in channel.commercials}

        self._cycle: list[_Seg] = []
        self._starts: list[float] = []
        self._total = 0.0
        self._windows: dict[tuple[str, int], tuple[list[_Seg], list[float], float, float, float]] = {}
        self._signature: tuple = ()
        self.rebuild()

    # ── pools ─────────────────────────────────────────────────────────────

    def _is_ad(self, video: VideoItem) -> bool:
        return video.id in self._ad_ids

    def _dur(self, video: VideoItem) -> float:
        d = 0.0
        try:
            d = float(self._duration_of(video) or 0.0)
        except Exception:
            d = 0.0
        if d < MIN_SEGMENT_S:
            d = float(getattr(video, "duration", 0.0) or 0.0)
        if d < MIN_SEGMENT_S:
            d = DEFAULT_AD_S if self._is_ad(video) else DEFAULT_PROGRAMME_S
        return d

    def _signature_now(self) -> tuple:
        try:
            return (tuple(round(self._dur(v), 1) for v in self.channel.videos)
                    + tuple(round(self._dur(c), 1) for c in self.channel.commercials)
                    + (datetime.date.today().toordinal(),))
        except Exception:
            return ()

    def invalidate(self) -> None:
        self._signature = ()

    def rebuild(self) -> None:
        self._signature = self._signature_now()
        self._windows.clear()
        if not self.dayparts:
            self._build_cycle()

    def rebuild_if_changed(self) -> bool:
        sig = self._signature_now()
        if sig != self._signature:
            self.rebuild()
            return True
        return False

    def _programme_pool(self, window: str) -> list[VideoItem]:
        if window == "main":
            return [v for v in self.channel.videos if not v.daypart]
        special = [v for v in self.channel.videos if v.daypart == window]
        main = [v for v in self.channel.videos if not v.daypart]
        return special + main

    def _ad_pool(self, window: Optional[str], when: datetime.datetime) -> list[VideoItem]:
        """Ads allowed at `when` in `window`; seasonal/daypart ads are boosted."""
        base: list[VideoItem] = []
        special: list[VideoItem] = []
        for ad in self.channel.commercials:
            season = getattr(ad, "season", "") or ""
            daypart = getattr(ad, "daypart", "") or ""
            if season and not season_active(season, when):
                continue
            if daypart and (window is None or daypart != window):
                continue
            (special if (season or daypart) else base).append(ad)
        pool = base + special + special
        if not pool:
            # Everything is seasonal and out of season: keep the channel on air.
            pool = [ad for ad in self.channel.commercials
                    if not getattr(ad, "season", "")]
            if not pool:
                pool = list(self.channel.commercials)
        return pool

    # ── building ──────────────────────────────────────────────────────────

    def _pod(self, video: VideoItem, pod_number: int, avoid_first: Optional[str],
             pool: list[VideoItem], seed: str) -> list[VideoItem]:
        if not pool or self.policy.max_ads <= 0:
            return []
        rng = random.Random(f"{self.channel.id}|{video.id}|{pod_number}|{seed}")
        n = rng.randint(self.policy.min_ads, self.policy.max_ads)
        n = max(0, min(n, len(pool)))
        if n == 0:
            return []
        if len(pool) <= n:
            picked = pool[:]
            rng.shuffle(picked)
        else:
            picked = rng.sample(pool, n)
        if avoid_first and len(picked) > 1 and picked[0].id == avoid_first:
            j = rng.randrange(1, len(picked))
            picked[0], picked[j] = picked[j], picked[0]
        return picked

    def _build_segments(self, videos: list[VideoItem], ad_pool: list[VideoItem],
                        seed: str) -> list[_Seg]:
        cycle: list[_Seg] = []
        prev_last_ad: Optional[str] = None
        pod_number = 0

        for pi, video in enumerate(videos):
            dur = self._dur(video)
            run = pod_number

            cuts: list[float] = []
            if self.policy.every_s > 0 and dur >= self.policy.min_video_s:
                t = self.policy.every_s
                while t <= dur - self.policy.tail_guard_s:
                    cuts.append(t)
                    t += self.policy.every_s

            pos = 0.0
            for bi, cut in enumerate(cuts):
                seg_len = cut - pos
                if seg_len >= MIN_SEGMENT_S:
                    cycle.append(_Seg("main", video, seg_len, pi, bi, -1, 0, pos, run))
                ads = self._pod(video, pod_number, prev_last_ad, ad_pool, seed)
                pod_number += 1
                for ai, ad in enumerate(ads):
                    cycle.append(_Seg("ad", ad, self._dur(ad), pi, bi, ai, len(ads), 0.0, run))
                if ads:
                    prev_last_ad = ads[-1].id
                pos = cut

            rest = dur - pos
            if rest >= MIN_SEGMENT_S:
                cycle.append(_Seg("main", video, rest, pi, -1, -1, 0, pos, run))

            ads = self._pod(video, pod_number, prev_last_ad, ad_pool, seed)
            pod_number += 1
            for ai, ad in enumerate(ads):
                cycle.append(_Seg("ad", ad, self._dur(ad), pi, len(cuts), ai, len(ads), 0.0, run))
            if ads:
                prev_last_ad = ads[-1].id

        return cycle

    def _build_cycle(self) -> None:
        pool = self._ad_pool(None, datetime.datetime.now())
        cycle = self._build_segments(list(self.channel.videos), pool, "cycle")
        starts: list[float] = []
        acc = 0.0
        for seg in cycle:
            starts.append(acc)
            acc += seg.length
        self._cycle = cycle
        self._starts = starts
        self._total = acc
        if not cycle:
            log.warning("Timeline for %s is empty (no videos)", self.channel.id)

    def _build_window(self, name: str, start_h: int, end_h: int, day_start: float):
        ws = day_start + start_h * 3600
        we = day_start + end_h * 3600
        when = datetime.datetime.fromtimestamp(ws + 60)
        pool = self._ad_pool(name, when)
        videos = self._programme_pool(name) or list(self.channel.videos)
        cycle = self._build_segments(videos, pool, f"{name}|{int(day_start // DAY_S)}")
        starts: list[float] = []
        acc = 0.0
        for seg in cycle:
            starts.append(acc)
            acc += seg.length
        return cycle, starts, acc, ws, we

    # ── day helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _day_floor(t: float) -> float:
        dt = datetime.datetime.fromtimestamp(t)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def _window_for(self, t: float):
        day = self._day_floor(t)
        hour = datetime.datetime.fromtimestamp(t).hour
        for name, sh, eh in self.windows:
            if sh <= hour < eh:
                return name, sh, eh, day
        name, sh, eh = self.windows[-1]
        return name, sh, eh, day

    def _layout(self, t: float):
        """(segs, starts, total, origin) for the layout that contains `t`."""
        if not self.dayparts:
            return self._cycle, self._starts, self._total, self.origin
        name, sh, eh, day = self._window_for(t)
        key = (name, int(day // DAY_S), int(sh))
        lay = self._windows.get(key)
        if lay is None:
            lay = self._build_window(name, sh, eh, day)
            self._windows[key] = lay
            if len(self._windows) > 6:
                for k in list(self._windows)[:len(self._windows) - 6]:
                    del self._windows[k]
        return lay[0], lay[1], lay[2], lay[3]

    # ── queries ───────────────────────────────────────────────────────────

    @property
    def cycle_length(self) -> float:
        if self.dayparts:
            return sum(seg.length for seg in self._layout(datetime.datetime.now().timestamp())[0])
        return self._total

    def _index_at(self, t: float):
        segs, starts, total, origin = self._layout(t)
        if not segs or total <= 0:
            return -1, t, segs
        elapsed = (t - origin) % total
        i = bisect.bisect_right(starts, elapsed) - 1
        if i < 0:
            i = 0
        seg_start = t - (elapsed - starts[i])
        return i, seg_start, segs

    def _airing(self, i: int, start: float, segs: list[_Seg]) -> Airing:
        seg = segs[i]
        return Airing(
            kind=seg.kind, video=seg.video,
            start=start, end=start + seg.length,
            programme_index=seg.programme_index, pod_index=seg.pod_index,
            ad_index=seg.ad_index, pod_len=seg.pod_len, segment_index=i,
            video_offset=seg.video_offset, run=seg.run,
        )

    def _clamp(self, airing: Airing, window_end: Optional[float]) -> Airing:
        if window_end is not None and airing.end > window_end:
            return replace(airing, end=window_end)
        return airing

    def _window_end(self, t: float) -> Optional[float]:
        if not self.dayparts:
            return None
        _name, _sh, eh, day = self._window_for(t)
        return day + eh * 3600

    def airing_at(self, t: float) -> Optional[Airing]:
        """The segment airing at epoch `t` (None for an empty channel)."""
        i, start, segs = self._index_at(t)
        if i < 0:
            return None
        air = self._airing(i, start, segs)
        return self._clamp(air, self._window_end(t))

    def next_after(self, airing: Optional[Airing]) -> Optional[Airing]:
        """The segment that starts where `airing` ends.

        v0.7.7: the probe time carries a 50 ms epsilon.  `airing_at(end)` sits
        exactly on a boundary, and the accumulated `starts` and the epoch maths
        disagree by a few ULPs, so bisect could land back on the *same* segment.
        Re-selecting the segment that just ended is what produced the
        “Join 30s is past the end (30s)” clamps and the one-second ad blinks.
        """
        if airing is None:
            return None
        t = max(airing.end, airing.start + MIN_SEGMENT_S) + 0.05
        nxt = self.airing_at(t)
        if nxt is not None and nxt.start <= airing.start + 0.001:
            # Still the same segment (a degenerate layout): step a whole length.
            nxt = self.airing_at(t + max(airing.length, MIN_SEGMENT_S))
        return nxt

    def airing_at_or_after(self, t: float,
                           airing: Optional[Airing] = None) -> Optional[Airing]:
        """The airing at `t`, walking forward from `airing` while it is over.

        v0.7.2: this is what stops the “same ad restarts every few seconds”
        loop.  When the player is late (a slow seek held the cover for 12 s), the
        segment after the current one can *also* already be over; jumping to it
        and seeking to `position_at(now)` means seeking past the end of the file,
        which never lands, which makes the player later still.  Walking forward
        until an airing's end is in the future breaks that feedback loop.
        """
        air = airing
        steps = 0
        while air is not None and air.end <= t and steps < 500:
            air = self.next_after(air)
            steps += 1
        if air is None or air.end <= t:
            air = self.airing_at(t)
        return air

    def airings(self, t0: float, t1: float, limit: int = 400) -> list[Airing]:
        """Every segment intersecting [t0, t1), in order."""
        out: list[Airing] = []
        t = t0
        guard = 0
        while t < t1 and guard < limit:
            i, start, segs = self._index_at(t)
            if i < 0:
                break
            we = self._window_end(t)
            while start < t1 and guard < limit:
                air = self._clamp(self._airing(i, start, segs), we)
                out.append(air)
                guard += 1
                if air.end <= start:          # zero-length guard
                    break
                start = air.end
                if we is not None and start >= we:
                    break                     # window over: new context
                i = (i + 1) % len(segs)
            if not out:
                break
            t = out[-1].end if out[-1].end > t else t + 60
        return out

    def programme_blocks(self, t0: float, t1: float, limit: int = 500) -> list[ProgrammeBlock]:
        """Programmes as a guide lists them: contiguous, ads included in the slot.

        The scan starts by walking back to the beginning of the programme airing
        at `t0`, so a window that opens mid-programme (or inside its pod) still
        gets that programme's real start and nothing is skipped.
        """
        if t1 <= t0:
            return []
        i, start, segs = self._index_at(t0)
        if i < 0:
            return []
        for _ in range(len(segs)):
            seg = segs[i]
            if seg.kind == "main" and seg.video_offset <= 0.01:
                break
            prev = (i - 1) % len(segs)
            i = prev
            start -= segs[prev].length

        blocks: list[ProgrammeBlock] = []
        for a in self.airings(start, t1, limit=limit * 8):
            if a.kind == "main":
                starts_programme = a.video_offset <= 0.01
                if (not blocks or starts_programme
                        or abs(blocks[-1].end - a.start) > 0.01):
                    if len(blocks) >= limit:
                        break
                    blocks.append(ProgrammeBlock(a.video, a.start, a.end,
                                                 a.programme_index, a.run))
                else:
                    blocks[-1].end = a.end
            elif blocks:
                blocks[-1].end = a.end
        while blocks and blocks[0].end <= t0:
            blocks.pop(0)
        return blocks


# ── per-channel policy ──────────────────────────────────────────────────────

def policy_for_channel(channel: Channel, base: AdPolicy, jitter_s: float = 120.0,
                       min_every_s: float = 300.0) -> AdPolicy:
    """The base policy for one channel.

    Order of precedence:
      1. `catalog/<CHANNEL>/channel.json` — "ad_every_min" (minutes; 0 = use the
         default, a negative value = no mid-roll breaks at all), "ad_min",
         "ad_max".
      2. the app defaults (± a deterministic jitter).

    The jitter exists so two channels never break at the same moment.
    """
    base = base.normalised()
    every = base.every_s

    explicit = float(getattr(channel, "ad_every_min", 0.0) or 0.0)
    if explicit < 0:
        every = 0.0
    elif explicit > 0:
        every = explicit * 60.0
    elif every > 0 and jitter_s > 0:
        h = (zlib.crc32(channel.id.encode("utf-8")) % 1000) / 1000.0   # 0..1
        every = max(min_every_s, every + (h * 2.0 - 1.0) * jitter_s)

    min_ads = int(getattr(channel, "ad_min", 0) or base.min_ads)
    max_ads = int(getattr(channel, "ad_max", 0) or base.max_ads)
    if min_ads <= 0 and max_ads <= 0:
        every = 0.0                      # no commercials at all for this channel

    return AdPolicy(every, min_ads, max_ads,
                    base.min_video_s, base.tail_guard_s).normalised()
