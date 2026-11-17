"""
diagnose_durations.py â€” why is the schedule joining the wrong place?

Compares, for every channel video:
    what the container says   (probe.py â€” no ffprobe needed)
    what libvlc says          (the number that used to poison the schedule)
    what schedule_state.json has cached

Any line marked MISMATCH explains a channel that seems to start from the
beginning of a video instead of mid-broadcast.

Usage:
    python scripts/diagnose_durations.py
    python scripts/diagnose_durations.py --catalog D:/TV/catalog
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.catalog import scan_real_folder                  # noqa: E402
from scripts.duration_probe import have_ffprobe, probe_with_vlc  # noqa: E402
from scripts.probe import plausible, probe_video              # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = 5.0


def fmt(seconds: float) -> str:
    if not seconds:
        return "?"
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog", default=str(PROJECT_ROOT / "catalog"))
    ap.add_argument("--state", default=str(PROJECT_ROOT / "schedule_state.json"))
    ap.add_argument("--no-vlc", action="store_true", help="skip the libvlc column (faster)")
    args = ap.parse_args()

    print("=" * 74)
    print("DURATION DIAGNOSTIC")
    print("=" * 74)
    print(f"ffprobe on PATH : {'yes â€” ' + str(shutil.which('ffprobe')) if have_ffprobe() else 'no (not needed)'}")

    state_path = Path(args.state)
    state = {}
    if state_path.exists():
        with state_path.open("r", encoding="utf-8") as f:
            state = json.load(f)
        print(f"state file      : {state_path}")
    else:
        print(f"state file      : {state_path} (missing â€” nothing cached yet)")

    try:
        catalog = scan_real_folder(args.catalog)
    except Exception as e:
        print(f"\nCannot read catalog at {args.catalog}: {e}")
        return 2
    print(f"catalog         : {args.catalog}")

    problems = 0
    for ch in catalog.channels:
        cached = state.get("channels", {}).get(ch.id, {}).get("durations", {})
        print(f"\n--- {ch.name}  (id: {ch.id}) ---")
        for v in ch.videos:
            size = Path(v.src).stat().st_size if Path(v.src).exists() else 0
            info = probe_video(v.src)
            container = info.duration if info else 0.0
            source = info.source if info else ""
            vlc_len = 0.0 if args.no_vlc else probe_with_vlc(v.src)
            cache = float(cached.get(v.id, 0.0))

            flags = []
            if container and not plausible(container, size):
                flags.append("container implausible")
            if vlc_len and not plausible(vlc_len, size):
                flags.append("libvlc IMPLAUSIBLE")
            if cache and container and abs(cache - container) > TOLERANCE:
                flags.append("cache != container")
            if vlc_len and container and abs(vlc_len - container) > TOLERANCE:
                flags.append("libvlc != container")
            if flags:
                problems += 1

            print(f"  {v.title[:52]}")
            print(f"    container: {fmt(container):>8} ({container:.1f}s)"
                  f"   libvlc: {fmt(vlc_len):>8} ({vlc_len:.1f}s)"
                  f"   cached: {fmt(cache):>8}")
            if source:
                print(f"    source: {source}, {size / 1e6:.1f} MB"
                      + (f"  <-- {'; '.join(flags)}" if flags else ""))

    print("\n" + "=" * 74)
    if problems:
        print(f"{problems} mismatch(es). Run:  python scripts/fix_durations.py")
        print("(the app also re-probes and re-anchors automatically on launch)")
    else:
        print("Everything agrees â€” the schedule is working from correct lengths.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
