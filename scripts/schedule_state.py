"""
schedule_state.py — Persistent "live TV" schedule state per channel (v0.3.4)

Each channel has a virtual schedule that has been "airing" since `start_time`.
When you tune in, the position is pure wall-clock arithmetic:

    position_in_loop = (now - start_time) % total_duration

v0.3.4 fixes (see HANDOVER notes):

  1. CONTINUITY. total_duration is the sum of every video's length. Whenever a
     length changed (default 30 min -> real length learned from VLC/ffprobe, a
     file added/removed/reordered) the modulo base changed and the channel
     JUMPED to a different video. Now every change goes through `_anchor()`,
     which re-computes `start_time` so the video that is airing RIGHT NOW stays
     airing at the same offset. After that, position is deterministic again.
  2. TRUSTED DURATIONS. Lengths probed with ffprobe/libvlc are "locked" and
     can't be overwritten by whatever VLC happens to report mid-playback
     (which could belong to an ad or the previous clip). Lengths learned during
     playback are only accepted if >= 1 s.
  3. STABLE START OFFSET. The first-run offset used Python's hash(), which is
     randomised per process. It now uses zlib.crc32 so a given channel id always
     gets the same offset.
  4. Catalog `VideoItem.duration` values (when > 0) are used instead of the
     30-minute default.

State file (schedule_state.json) stores per channel: start_time, durations,
locked (ids whose duration came from a probe), order (ids in schedule order).
Old files load fine; unknown keys are ignored.
"""

from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
import zlib
from dataclasses import dataclass, field, asdict
from pathlib import Path

log = logging.getLogger("schedule_state")


@dataclass
class ChannelSchedule:
    start_time: float = 0.0                      # epoch seconds when channel "started airing"
    durations: dict = field(default_factory=dict)  # video_id -> seconds
    locked: list = field(default_factory=list)     # ids with probe-verified durations
    order: list = field(default_factory=list)      # video ids in the order last scheduled


class ScheduleState:
    """All channels' schedule state, persisted to JSON. Thread-safe (the
    duration probe runs on a background thread)."""

    DEFAULT_VIDEO_DURATION = 1800  # 30 min, only when nothing better is known
    MIN_DURATION = 1.0             # ignore bogus lengths below this
    SAME_EPSILON = 1.5             # durations closer than this are "unchanged"

    def __init__(self):
        self.channels: dict[str, ChannelSchedule] = {}
        self._lock = threading.RLock()
        self.last_debug: dict = {}   # details of the last compute (for logging)

    # ── persistence ──────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path) -> "ScheduleState":
        state = cls()
        if not path.exists():
            log.info("No schedule_state.json found — initializing fresh state")
            return state
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            for ch_id, ch_data in data.get("channels", {}).items():
                known = {k: v for k, v in ch_data.items()
                         if k in ChannelSchedule.__dataclass_fields__}
                sched = ChannelSchedule(**known)
                sched.durations = {k: float(v) for k, v in (sched.durations or {}).items()
                                   if _good(v)}
                sched.locked = [i for i in (sched.locked or []) if i in sched.durations]
                sched.order = list(sched.order or [])
                state.channels[ch_id] = sched
        except Exception as e:
            log.warning(f"Failed to load schedule_state.json ({e}); starting fresh")
            state.channels.clear()
        return state

    def save(self, path: Path):
        with self._lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                data = {"channels": {k: asdict(v) for k, v in self.channels.items()}}
                tmp = path.with_suffix(path.suffix + ".tmp")
                with tmp.open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                tmp.replace(path)   # atomic on the same volume — no half-written file
            except Exception as e:
                log.warning(f"Failed to save schedule_state.json: {e}")

    # ── init / lookup ────────────────────────────────────────────────────

    @staticmethod
    def _initial_offset(channel_id: str) -> float:
        """Deterministic 0-3600 s offset per channel id (NOT hash(): that is
        randomised per process)."""
        return random.Random(zlib.crc32(channel_id.encode("utf-8"))).uniform(0, 3600)

    def get_or_init(self, channel_id: str) -> ChannelSchedule:
        with self._lock:
            sched = self.channels.get(channel_id)
            if sched is None:
                sched = ChannelSchedule(start_time=time.time() - self._initial_offset(channel_id))
                self.channels[channel_id] = sched
            elif sched.start_time == 0:
                sched.start_time = time.time() - self._initial_offset(channel_id)
            return sched

    def get_duration(self, channel_id: str, video_id: str) -> float:
        with self._lock:
            sched = self.channels.get(channel_id)
            d = sched.durations.get(video_id, 0) if sched else 0
            return float(d) if d else float(self.DEFAULT_VIDEO_DURATION)

    def known_duration(self, channel_id: str, video_id: str) -> float:
        """Stored length in seconds, or 0.0 when nothing is known yet.

        Unlike get_duration(), this does NOT substitute the 30-minute default —
        callers that must not divide by a guess (the seek math in app.py) need
        to tell the two apart.
        """
        with self._lock:
            sched = self.channels.get(channel_id)
            if not sched:
                return 0.0
            return float(sched.durations.get(video_id) or 0.0)

    def is_locked(self, channel_id: str, video_id: str) -> bool:
        with self._lock:
            sched = self.channels.get(channel_id)
            return bool(sched and video_id in sched.locked)

    # ── core math ────────────────────────────────────────────────────────

    def _durs(self, sched: ChannelSchedule, ids: list) -> list:
        return [float(sched.durations.get(i) or self.DEFAULT_VIDEO_DURATION) for i in ids]

    def _locate(self, sched: ChannelSchedule, ids: list, now: float):
        """(index, seconds_into_video, total_loop, elapsed) airing at `now`."""
        durs = self._durs(sched, ids)
        total = sum(durs)
        elapsed = max(0.0, now - sched.start_time)
        if total <= 0:
            return 0, 0.0, 0.0, elapsed
        loop = elapsed % total
        for i, d in enumerate(durs):
            if loop < d:
                return i, loop, total, elapsed
            loop -= d
        return 0, 0.0, total, elapsed

    def _anchor(self, sched: ChannelSchedule, ids: list, idx: int, pos: float, now: float):
        """Re-aim start_time so (ids[idx], pos) is what airs at `now`."""
        durs = self._durs(sched, ids)
        pos = max(0.0, min(pos, durs[idx] - 1.0)) if durs[idx] > 1.0 else 0.0
        sched.start_time = now - (sum(durs[:idx]) + pos)

    # ── durations ────────────────────────────────────────────────────────

    def set_duration(self, channel_id: str, video_id: str, duration_seconds: float,
                     source: str = "play") -> bool:
        """Record a video's length. source: "probe" (authoritative, locked),
        "catalog" or "play" (learned from the player; ignored if locked).
        Keeps the currently-airing video airing (no jump). Returns True if
        the stored value changed."""
        if not _good(duration_seconds) or duration_seconds < self.MIN_DURATION:
            return False
        with self._lock:
            sched = self.get_or_init(channel_id)
            if source != "probe" and video_id in sched.locked:
                return False
            old = sched.durations.get(video_id)
            if source == "probe" and video_id not in sched.locked:
                sched.locked.append(video_id)
            if old and abs(old - duration_seconds) <= self.SAME_EPSILON:
                return False
            ids = sched.order
            if ids and video_id in ids:
                now = time.time()
                idx, pos, _, _ = self._locate(sched, ids, now)   # airing under OLD lengths
                sched.durations[video_id] = float(duration_seconds)
                self._anchor(sched, ids, idx, pos, now)           # ...stays airing
            else:
                sched.durations[video_id] = float(duration_seconds)
            return True

    def compute_live_position(self, channel_id: str, videos: list) -> tuple[int, float]:
        """Where playback should be RIGHT NOW. `videos` = the channel's main
        videos in schedule order. Returns (video_idx, seconds_into_video)."""
        with self._lock:
            sched = self.get_or_init(channel_id)
            if not videos:
                self.last_debug = {}
                return (0, 0.0)
            now = time.time()
            ids = [v.id for v in videos]

            # (1) catalog changed (file added / removed / reordered): keep the
            #     airing video airing if it still exists
            if sched.order and sched.order != ids:
                oi, opos, _, _ = self._locate(sched, sched.order, now)
                airing = sched.order[oi]
                sched.order = ids
                if airing in ids:
                    self._anchor(sched, ids, ids.index(airing), opos, now)
                    log.info("%s: catalog changed — kept '%s' airing", channel_id, airing)
            sched.order = ids

            # (2) seed lengths from the catalog (VideoItem.duration) when known
            for v in videos:
                d = getattr(v, "duration", 0.0) or 0.0
                if d >= self.MIN_DURATION and v.id not in sched.durations:
                    self.set_duration(channel_id, v.id, d, source="catalog")

            idx, pos, total, elapsed = self._locate(sched, ids, now)
            self.last_debug = {
                "channel": channel_id, "now": round(now, 1),
                "start_time": round(sched.start_time, 1),
                "elapsed_s": round(elapsed, 1), "loop_total_s": round(total, 1),
                "video_idx": idx, "video_id": ids[idx], "position_s": round(pos, 1),
                "known_durations": f"{len([i for i in ids if i in sched.durations])}/{len(ids)}",
                "locked": f"{len([i for i in ids if i in sched.locked])}/{len(ids)}",
            }
            log.debug("compute_live_position %s", self.last_debug)
            return (idx, pos)


def _good(v) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0
