"""
check_commercials.py â€” what each channel will actually air, and when

v0.7.0: the app no longer builds a queue and fires mid-rolls from a timer; every
channel has a broadcast timeline (scripts/timeline.py) with the ad pods baked
into it.  This tool prints that timeline, because that is the only thing that
explains what you see on screen:

    * the channel's ad policy (interval, pod size) â€” per channel, not global,
    * the cycle length (programme + pods, one loop),
    * the next three hours of airings, M = programme, A = commercial,
    * the first time each programme starts, so you can see the rotation.

Usage:
    python scripts/check_commercials.py
    python scripts/check_commercials.py --catalog D:/TV/catalog
    python scripts/check_commercials.py --hours 6
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.catalog import CATALOG_AUXILIARY_FOLDER_NAMES, scan_real_folder  # noqa: E402
from scripts.schedule_state import ScheduleState                                # noqa: E402
from scripts.duration_probe import probe_channel                                # noqa: E402
from scripts.timeline import AdPolicy, ChannelTimeline, policy_for_channel      # noqa: E402

AUX_HINT = ", ".join(sorted(CATALOG_AUXILIARY_FOLDER_NAMES))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog", default=str(Path(__file__).resolve().parent.parent / "catalog"))
    ap.add_argument("--hours", type=float, default=3.0)
    args = ap.parse_args()

    root = Path(args.catalog)
    print("=" * 72)
    print("COMMERCIAL / TIMELINE DIAGNOSTIC")
    print("=" * 72)
    print(f"catalog: {root}")
    if not root.exists():
        print("  -> folder does not exist")
        return 2

    base_every = float(os.environ.get("NULLA_AD_BREAK_MINUTES", "10")) * 60.0
    ads_min = int(os.environ.get("NULLA_AD_MIN", "5"))
    ads_max = max(ads_min, int(os.environ.get("NULLA_AD_MAX", "10")))
    base = AdPolicy(base_every, ads_min, ads_max, 20 * 60, 90)
    print(f"defaults : every {base_every/60:.0f} min, {ads_min}-{ads_max} ads, "
          f"videos >= 20 min, {90}s tail guard")
    print("           (each channel shifts the interval by up to Â±2 min)")
    print()

    catalog = scan_real_folder(root)
    if not catalog.channels:
        print("No channels found. Each sub-folder of the catalog is a channel:")
        print("    catalog/<CHANNEL>/video.mp4")
        print(f"    catalog/<CHANNEL>/Commercials/*.mp4   (also: {AUX_HINT})")
        print("Optional per-channel settings: catalog/<CHANNEL>/channel.json")
        return 1

    state = ScheduleState.load(Path(__file__).resolve().parent.parent / "schedule_state.json")
    now = time.time()

    for ch in catalog.channels:
        try:
            probe_channel(state, ch, allow_vlc=False)
        except Exception:
            pass
        policy = policy_for_channel(ch, base, jitter_s=120.0)
        origin = state.get_or_init(ch.id).start_time

        def dur(v, _ch=ch):
            d = state.known_duration(_ch.id, v.id)
            return d or float(getattr(v, "duration", 0.0) or 0.0)

        tl = ChannelTimeline(ch, dur, policy, origin)
        pods = sum(1 for a in tl.airings(now, now + tl.cycle_length, limit=4000)
                   if a.kind == "ad")
        print(f"[{ch.number:02d}] {ch.name}   {len(ch.videos)} programme(s), "
              f"{len(ch.commercials)} ad(s) in the pool")
        if policy.every_s <= 0:
            print("     ads: none (mid-rolls disabled for this channel)")
        else:
            print(f"     ads: every {policy.every_s/60:.1f} min, "
                  f"{policy.min_ads}-{policy.max_ads} per break, "
                  f"{pods} in one cycle")
        print(f"     cycle: {tl.cycle_length/60:.1f} min")
        if not ch.commercials:
            print("     WARNING: no Commercials/ folder -> nothing to break with")

        line = []
        for a in tl.airings(now, now + args.hours * 3600, limit=400):
            stamp = datetime.datetime.fromtimestamp(a.start).strftime("%H:%M:%S")
            if a.kind == "main":
                line.append(f"{stamp} M {a.video.title[:26]}")
            else:
                line.append(f"{stamp} A {a.video.title[:26]}")
        print("     next airings:")
        for row in line[:40]:
            print("       " + row)
        if len(line) > 40:
            print(f"       â€¦ {len(line)-40} more")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
