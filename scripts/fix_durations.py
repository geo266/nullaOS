"""
fix_durations.py â€” repair schedule_state.json using the real files on disk

The old version guessed from filenames and fell back to 30 minutes.  This one
asks the container itself (probe.py) for each cached video's true length, so
the cached numbers end up matching the files.

Typical use: you upgraded from a version that let libvlc write a 37-hour
length for a 44-minute file, and the channel keeps joining the wrong place.

Usage:
    python scripts/fix_durations.py                     (uses ./catalog)
    python scripts/fix_durations.py --catalog D:/TV/catalog
    python scripts/fix_durations.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.catalog import scan_real_folder          # noqa: E402
from scripts.probe import (duration_hint, plausible, probe_video)  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "schedule_state.json"
TOLERANCE = 1.5          # seconds â€” closer than this counts as "same"


def fmt(seconds: float) -> str:
    if not seconds:
        return "?"
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def best_duration(path: str) -> tuple[float, str]:
    """(duration, where_it_came_from) from the container, then the filename."""
    info = probe_video(path)
    if info and info.duration > 0:
        return info.duration, info.source
    hint = duration_hint(path)
    if hint and plausible(hint, Path(path).stat().st_size):
        return hint, "filename"
    return 0.0, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog", default=str(PROJECT_ROOT / "catalog"))
    ap.add_argument("--state", default=str(STATE_FILE))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"No schedule state at {state_path} â€” nothing to repair.")
        return 0

    catalog = scan_real_folder(args.catalog)
    by_id: dict[str, str] = {}
    for ch in catalog.channels:
        for v in ch.videos:
            by_id.setdefault(v.id, v.src)

    with state_path.open("r", encoding="utf-8") as f:
        state = json.load(f)

    changed = 0
    unknown = 0
    for ch_id, ch_data in state.get("channels", {}).items():
        durations = ch_data.get("durations", {})
        locked = set(ch_data.get("locked", []))
        for video_id, cached in list(durations.items()):
            src = by_id.get(video_id)
            if not src:
                unknown += 1
                continue
            real, source = best_duration(src)
            if real <= 0:
                continue
            if cached and abs(cached - real) <= TOLERANCE:
                continue
            print(f"  {video_id[:58]}")
            print(f"    cached: {fmt(cached)} ({cached:.1f}s)"
                  f"  ->  real: {fmt(real)} ({real:.1f}s)  [{source}]")
            durations[video_id] = round(real, 3)
            locked.add(video_id)
            changed += 1
        ch_data["locked"] = sorted(locked)

    if not changed:
        print("All cached durations already match the files.")
        if unknown:
            print(f"({unknown} cached id(s) no longer exist in the catalog.)")
        return 0

    print(f"\n{changed} duration(s) corrected" +
          (" â€” dry run, nothing written." if args.dry_run else "."))
    if not args.dry_run:
        tmp = state_path.with_suffix(state_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        tmp.replace(state_path)
        print(f"Wrote {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
