"""
playlist.py — Build a play queue with random commercial injection

The user's spec: "When playing a channel, randomly inject 1-2 commercial videos
from that channel's specific commercial pool between main video files."

This module takes a Channel and produces an ordered list of play items, where
between every pair of consecutive main videos we insert 1-2 (configurable)
random commercials drawn WITHOUT replacement from that channel's pool.

The output is a list of PlayItem dicts with a 'kind' field so the player UI
can render the right overlay (main = Xfinity-style now-playing banner,
ad = TiVo-style "COMMERCIAL BREAK" tag).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from catalog import Channel, VideoItem


@dataclass
class PlayItem:
    """A single item in the play queue, with metadata for the UI to render."""
    kind: str            # "main" | "ad" | "bumper"
    video: VideoItem
    # Optional schedule metadata, filled in by the player at runtime
    scheduled_start: Optional[float] = None  # epoch seconds
    scheduled_end: Optional[float] = None


def _shuffle_no_replace(pool: list[VideoItem], n: int, rng: random.Random) -> list[VideoItem]:
    """Pick n items from pool, without replacement (so no commercial repeats
    in the same break). If pool is smaller than n, returns the whole pool
    shuffled (degraded gracefully)."""
    if not pool or n <= 0:
        return []
    n = min(n, len(pool))
    copy = list(pool)
    rng.shuffle(copy)
    return copy[:n]


def next_break_position(position_s: float, every_s: float, min_gap_s: float = 60.0) -> float:
    """Video position (seconds) of the next mid-roll break.

    Breaks sit at fixed points in the show (every_s, 2*every_s, ...) instead of
    "every_s after you tuned in", so a channel breaks at the same moments no
    matter when you join - like broadcast.  If joining would put the next break
    closer than min_gap_s, skip to the one after.  every_s <= 0 disables breaks
    (returns 0.0, which callers treat as "never")."""
    if every_s <= 0:
        return 0.0
    nxt = (int(position_s // every_s) + 1) * every_s
    if nxt - position_s < min_gap_s:
        nxt += every_s
    return float(nxt)


def build_ad_break(
    channel: Channel,
    min_ads: int = 1,
    max_ads: int = 2,
    rng: Optional[random.Random] = None,
    avoid_first_id: Optional[str] = None,
) -> list[PlayItem]:
    """A standalone commercial break, drawn from the channel's own pool.

    avoid_first_id: id of the ad that closed the previous break; the new break
    will not open with it (when the pool has an alternative).

    Used for mid-roll breaks: a channel whose only video is 4 hours long never
    reaches a "between videos" point, so the break has to happen *inside* the
    video (app.py interrupts, plays these, then resumes).
    """
    rng = rng or random.Random()
    if not channel.commercials or max_ads <= 0:
        return []
    n = rng.randint(max(0, min_ads), max_ads)
    picked = _shuffle_no_replace(channel.commercials, n, rng)
    if avoid_first_id and len(picked) > 1 and picked[0].id == avoid_first_id:
        # swap the opener with a later ad so the same spot doesn't play twice in a row
        j = rng.randrange(1, len(picked))
        picked[0], picked[j] = picked[j], picked[0]
    return [PlayItem(kind="ad", video=v) for v in picked]


def build_playlist(
    channel: Channel,
    min_ads: int = 1,
    max_ads: int = 2,
    rng: Optional[random.Random] = None,
    insert_after_last: bool = False,
) -> list[PlayItem]:
    """Build the play queue for a channel.

    Args:
        channel:           The Channel to play. Uses channel.videos as main
                            content and channel.commercials as the pool.
        min_ads:           Minimum commercials per break (default 1).
        max_ads:           Maximum commercials per break (default 2).
        rng:               Optional seeded RNG for reproducibility (useful in
                            tests; in production, leave None for system entropy).
        insert_after_last: If False (default), do NOT insert a commercial block
                            after the last main video — the queue just ends, or
                            loops back to the first main video on next().
                            If True, insert a final ad block before looping.

    Returns:
        Ordered list[PlayItem] with 'main' and 'ad' items interleaved.

    Raises:
        ValueError if min_ads > max_ads or min_ads < 0.
    """
    if min_ads < 0 or max_ads < 0:
        raise ValueError("min_ads and max_ads must be >= 0")
    if min_ads > max_ads:
        raise ValueError(f"min_ads ({min_ads}) > max_ads ({max_ads})")

    rng = rng or random.Random()
    out: list[PlayItem] = []

    n_videos = len(channel.videos)
    if n_videos == 0:
        return out

    for i, video in enumerate(channel.videos):
        out.append(PlayItem(kind="main", video=video))

        # Decide whether to insert an ad block after this video
        is_last = (i == n_videos - 1)
        should_insert = (not is_last) or insert_after_last

        if should_insert and channel.commercials:
            n = rng.randint(min_ads, max_ads)
            picks = _shuffle_no_replace(channel.commercials, n, rng)
            for pick in picks:
                out.append(PlayItem(kind="ad", video=pick))

    return out


# ── Helpers for the UI ─────────────────────────────────────────────────────

def is_commercial_break(items: list[PlayItem], idx: int) -> bool:
    """True if the item at idx is an ad AND surrounded by other ads (i.e. we're
    mid-break, not a lone bumper). Used by the UI to show 'COMMERCIAL BREAK'
    overlay vs a single tagged item."""
    if idx < 0 or idx >= len(items):
        return False
    if items[idx].kind != "ad":
        return False
    # At least 2 consecutive ads = a 'break'
    prev_ad = (idx > 0 and items[idx - 1].kind == "ad")
    next_ad = (idx + 1 < len(items) and items[idx + 1].kind == "ad")
    return prev_ad or next_ad


def ad_break_count(items: list[PlayItem]) -> int:
    """Count distinct ad breaks (groups of consecutive ads) in the queue."""
    count = 0
    in_break = False
    for item in items:
        if item.kind == "ad":
            if not in_break:
                count += 1
                in_break = True
        else:
            in_break = False
    return count


def ad_count_in_break(items: list[PlayItem], idx: int) -> int:
    """How many ads are in the break containing idx (inclusive of idx)."""
    if idx < 0 or idx >= len(items) or items[idx].kind != "ad":
        return 0
    # Walk back to break start
    start = idx
    while start > 0 and items[start - 1].kind == "ad":
        start -= 1
    # Walk forward to break end
    end = idx
    while end + 1 < len(items) and items[end + 1].kind == "ad":
        end += 1
    return end - start + 1


def position_in_break(items: list[PlayItem], idx: int) -> tuple[int, int]:
    """Return (position, total) — e.g. (2, 3) means '2nd of 3 ads in this break'.
    Used for the 'You're watching an ad — 2 of 3' overlay."""
    total = ad_count_in_break(items, idx)
    if total == 0:
        return (0, 0)
    start = idx
    while start > 0 and items[start - 1].kind == "ad":
        start -= 1
    return (idx - start + 1, total)


# ── Smoke test ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from catalog import Channel, VideoItem

    ch = Channel(
        id="test",
        number=1,
        name="TEST",
        abbrev="TST",
        videos=[
            VideoItem(id=f"v{i}", title=f"Ep {i}", src=f"ep{i}.mp4", duration=60 * i)
            for i in range(1, 5)
        ],
        commercials=[
            VideoItem(id=f"c{i}", title=f"Ad {i}", src=f"ad{i}.mp4", duration=30)
            for i in range(1, 4)
        ],
    )

    rng = random.Random(42)  # reproducible for the test
    queue = build_playlist(ch, min_ads=1, max_ads=2, rng=rng)

    print(f"Channel {ch.name}: {len(ch.videos)} videos, {len(ch.commercials)} commercials")
    print(f"Built queue of {len(queue)} items ({ad_break_count(queue)} ad breaks):\n")
    for i, item in enumerate(queue):
        marker = "  " if item.kind == "main" else "  AD"
        if item.kind == "ad":
            pos, tot = position_in_break(queue, i)
            marker += f" [{pos}/{tot}]"
        print(f"  {i:2d}.{marker}  {item.video.title}")
