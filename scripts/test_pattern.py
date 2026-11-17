"""
test_pattern.py — Generate SMPTE color bars + 1kHz tone as MP4 fallback content

When you haven't dropped your own test videos into assets/mock/ yet, this
script generates a small MP4 for every path in catalog.json (both channels
and library) so the app boots and the playback loop / ad-injection /
library browse / VLC rendering can be verified end-to-end before you
supply real content.

Requires ffmpeg in PATH. Run from project root:
    python scripts/test_pattern.py

Channel videos get the channel abbrev + title burned in.
Commercial clips get an [AD] tag (and the channel source region like "JP:"
or "USA:") so you can visually verify per-channel commercial isolation.
Library movies and show episodes get a "LIBRARY" tag.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = PROJECT_ROOT / "assets" / "mock" / "catalog.json"


def smpte_bars_command(output_path: Path, duration_s: int, caption: str = "") -> list[str]:
    """Build an ffmpeg command producing an SMPTE-bars MP4 at 720x480 4:3 NTSC."""
    vf_chain = ["scale=720:480,setsar=1"]
    if caption:
        safe = caption.replace(":", "\\:").replace("'", "\\'")
        vf_chain.append(
            f"drawtext=text='{safe}':fontcolor=white:fontsize=48:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5"
        )
    return [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "smptebars=duration={}:size=720x480:rate=30000/1001".format(duration_s),
        "-f", "lavfi", "-i", "sine=frequency=1000:duration={}:sample_rate=48000".format(duration_s),
        "-vf", ",".join(vf_chain),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]


def main():
    if not CATALOG_PATH.exists():
        print(f"ERROR: catalog not found at {CATALOG_PATH}")
        return 1

    with CATALOG_PATH.open("r", encoding="utf-8") as f:
        catalog = json.load(f)

    # CAP TEST PATTERN DURATIONS — the catalog has realistic durations
    # (e.g. 5760s for a 96-min movie) which would generate huge slow MP4s.
    # For test patterns we just need enough runtime to verify the playback
    # loop and ad injection — 30-60s is plenty. Override per-item.
    MAX_TEST_DURATION = 10   # seconds; bump if you need longer verification clips

    generated = 0
    skipped = 0
    failed = 0

    # ── Channel videos + commercials (TV mode) ───────────────────────────
    for channel in catalog.get("channels", []):
        for video in channel.get("videos", []):
            src = PROJECT_ROOT / video["src"]
            duration = min(int(video.get("duration") or 30), MAX_TEST_DURATION)
            if src.exists():
                print(f"  SKIP (already exists): {src}")
                skipped += 1
                continue
            src.parent.mkdir(parents=True, exist_ok=True)
            caption = f"{channel['abbrev']}  {video['title']}"
            cmd = smpte_bars_command(src, duration, caption=caption)
            print(f"  GEN [TV video]:  {src}  ({duration}s, '{caption}')")
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                generated += 1
            except subprocess.CalledProcessError as e:
                print(f"    FAILED: {e.stderr.decode('utf-8', errors='replace')[:300]}")
                failed += 1

        for ad in channel.get("commercials", []):
            src = PROJECT_ROOT / ad["src"]
            duration = min(int(ad.get("duration") or 30), MAX_TEST_DURATION)
            if src.exists():
                print(f"  SKIP (already exists): {src}")
                skipped += 1
                continue
            src.parent.mkdir(parents=True, exist_ok=True)
            # Caption preserves the region tag from catalog.json (e.g. "JP:", "USA:")
            # so you can visually verify per-channel commercial isolation.
            caption = f"[AD]  {ad['title']}"
            cmd = smpte_bars_command(src, duration, caption=caption)
            print(f"  GEN [commercial]:  {src}  ({duration}s, '{caption}')")
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                generated += 1
            except subprocess.CalledProcessError as e:
                print(f"    FAILED: {e.stderr.decode('utf-8', errors='replace')[:300]}")
                failed += 1

    # ── Library movies + show episodes (Browser mode) ─────────────────────
    library = catalog.get("library", {})
    for movie in library.get("movies", []):
        src = PROJECT_ROOT / movie["src"]
        duration = min(int(movie.get("duration") or 60), MAX_TEST_DURATION)
        if src.exists():
            print(f"  SKIP (already exists): {src}")
            skipped += 1
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        caption = f"[LIBRARY]  {movie['title']}"
        cmd = smpte_bars_command(src, duration, caption=caption)
        print(f"  GEN [movie]:  {src}  ({duration}s, '{caption}')")
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            generated += 1
        except subprocess.CalledProcessError as e:
            print(f"    FAILED: {e.stderr.decode('utf-8', errors='replace')[:300]}")
            failed += 1

    for show in library.get("shows", []):
        for ep in show.get("episodes", []):
            src = PROJECT_ROOT / ep["src"]
            duration = min(int(ep.get("duration") or 60), MAX_TEST_DURATION)
            if src.exists():
                print(f"  SKIP (already exists): {src}")
                skipped += 1
                continue
            src.parent.mkdir(parents=True, exist_ok=True)
            caption = f"[LIBRARY]  {show['title']} - {ep['title']}"
            cmd = smpte_bars_command(src, duration, caption=caption)
            print(f"  GEN [episode]:  {src}  ({duration}s, '{caption}')")
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                generated += 1
            except subprocess.CalledProcessError as e:
                print(f"    FAILED: {e.stderr.decode('utf-8', errors='replace')[:300]}")
                failed += 1

    print(f"\nDone. Generated: {generated}, Skipped: {skipped}, Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
