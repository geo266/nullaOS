"""
cover_wait.py — when is the tuning / resume cover allowed to come off?

The cover is the full-frame snow on a channel change and the black plate when a
video resumes after a commercial break.  It hides VLC while the new media is
loaded and seeked.

The bug this module exists for (v0.6.5, Kawaii TV): `get_time()` reaching the
target only proves the *demuxer* is there.  The video output can still be
holding the previous picture — the previous channel, a commercial, or frame 0
of the episode — so releasing the cover on a stopwatch (or on the first correct
timestamp) showed "one frame of a clip" for about a second before the episode
actually started.  It only ever showed on the 44-minute MPEG-PS captures,
because those take seconds to seek, not milliseconds.

Rule: release only when the position is at the target (or, when joining at
0:00, when the new media has actually played a little) **and** the clock moved
between two polls — that is the only signal we have that the decoder is
rolling new frames.  Give up after a hard deadline so a broken file cannot
leave the screen covered forever.

Pure logic: no Qt, no VLC.  `app.py` feeds it one call per 100 ms poll and
`test_cover_wait.py` feeds it simulated polls.
"""

from __future__ import annotations

from typing import Optional

#: Keep waiting (the caller may still need to seek; see app.py).
WAIT = "wait"
#: The picture is real — lift the cover.
RELEASE = "release"
#: The file never got there — lift the cover anyway, loudly.
GIVE_UP = "give_up"


class CoverWait:
    """Decide when a cover may be lifted.

    Parameters
    ----------
    target_s:
        Where in the media playback should be.  0 means "joined at the start":
        there is nothing to seek, we are only waiting for frames.
    first_frame_s:
        With target 0, the position the media must reach before we believe a
        picture exists (VLC reports 0 until the first frame is decoded).
    confirm_s:
        How much the clock must advance between two polls after reaching the
        target.  A frozen vout does not advance, so this rejects it.
    confirm_polls:
        How many *consecutive* advancing polls are required.  Two polls at the
        app's 100 ms rate means ~200 ms of decoded playback — long enough for a
        stale picture to have been replaced before anyone sees it.
    stall_s:
        If the clock sits at the target without advancing this long, assume it
        is frozen and let the picture through (better than a stuck cover).
    min_hold_s:
        Never release sooner than this after the position first reached the
        target.  A big MPEG-PS can report the right time a second before its
        video output shows the corresponding frame; this window absorbs that.
    deadline_s:
        Hard cap, measured from the first poll.
    tolerance_early / tolerance_late:
        How close to the target counts as "there", before / after the first seek
        has been issued.  MPEG-PS seeks land within a GOP, not exactly.
    """

    def __init__(self, target_s: float, *,
                 first_frame_s: float = 0.35,
                 confirm_s: float = 0.08,
                 confirm_polls: int = 2,
                 stall_s: float = 1.5,
                 deadline_s: float = 12.0,
                 min_hold_s: float = 0.0,
                 tolerance_early: float = 4.0,
                 tolerance_late: float = 10.0):
        self.target_s = max(0.0, float(target_s))
        self.first_frame_s = float(first_frame_s)
        self.confirm_s = float(confirm_s)
        self.confirm_polls = max(1, int(confirm_polls))
        self.stall_s = float(stall_s)
        self.deadline_s = float(deadline_s)
        self.min_hold_s = max(0.0, float(min_hold_s))
        self.tolerance_early = float(tolerance_early)
        self.tolerance_late = float(tolerance_late)

        self._started: Optional[float] = None
        self._landed_at: Optional[float] = None
        self._last_position: float = 0.0
        #: True once the position was seen at the target at least once.
        self.landed: bool = False
        #: Advancing polls seen since landing (released at confirm_polls).
        self.confirmations: int = 0
        #: Polls spent at the target without the clock moving.
        self.polls_at_target: int = 0

    # ── query ─────────────────────────────────────────────────────────────

    def at_target(self, position_s: float) -> bool:
        """Is `position_s` close enough to where we want to be?"""
        if self.target_s <= 0:
            return position_s >= self.first_frame_s
        tolerance = (self.tolerance_early if not self.landed
                     else self.tolerance_late)
        return abs(position_s - self.target_s) <= tolerance

    def elapsed(self, now: float) -> float:
        return 0.0 if self._started is None else now - self._started

    # ── state machine ─────────────────────────────────────────────────────

    def update(self, now: float, position_s: float, loaded: bool) -> str:
        """One poll.  Returns WAIT, RELEASE or GIVE_UP."""
        if self._started is None:
            self._started = now

        if loaded and self.at_target(position_s):
            self.landed = True
            if self._landed_at is None:
                # First poll that says "here".  The next ones have to prove the
                # clock is still moving before we trust the picture.
                self._landed_at = now
                self._last_position = position_s
                self.confirmations = 0
                self.polls_at_target = 1
                return WAIT

            self.polls_at_target += 1
            if position_s > self._last_position + self.confirm_s:
                self._last_position = position_s
                self.confirmations += 1
                if (self.confirmations >= self.confirm_polls
                        and (now - self._landed_at) >= self.min_hold_s):
                    return RELEASE
                return WAIT
            if now - self._landed_at > self.stall_s:
                return GIVE_UP
            return WAIT

        if self.landed:
            # It was there and then moved away (a corrective seek, or a seek
            # that landed in the wrong place): start the confirmation again.
            self.landed = False
            self._landed_at = None
            self._last_position = 0.0
            self.confirmations = 0
            self.polls_at_target = 0

        if self.elapsed(now) > self.deadline_s:
            return GIVE_UP
        return WAIT
