"""
duration_probe.py — find real video lengths BEFORE they're needed (v0.5)

The live-TV schedule needs every video's length to compute "what's airing now".
Learning lengths only while playing means the schedule changes under your feet —
and libvlc itself is not trustworthy for every container: it reports 37 hours
for a 44-minute MPEG-PS capture (broken timestamps), which used to poison
schedule_state.json.

Probe order (first hit wins):

  1. container header      — probe.py, pure Python, reads a few hundred KB
                              (mp4/mov/m4v, mkv/webm, avi, mpg/mpeg)
  2. ffprobe               — only if it happens to be on PATH
  3. filename hint         — "44′40", "1h02m33s", "44分40秒", "01:02:33"
  4. libvlc metadata       — last resort, and only if the value is consistent
                              with the file size (`probe.plausible`)

Every candidate is passed through `plausible()` (bitrate window), so a broken
timestamp can no longer be written into the schedule.

Results go into ScheduleState.set_duration(..., source="probe"), which locks
them and re-anchors the schedule so nothing visibly jumps.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Optional

from .probe import duration_hint, plausible, probe_video

log = logging.getLogger("duration_probe")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # no console flash on Windows
MIN_SANE_DURATION = 1.0


def have_ffprobe() -> bool:
    return shutil.which("ffprobe") is not None


def probe_with_ffprobe(path: str, timeout: float = 15.0) -> float:
    exe = shutil.which("ffprobe")
    if not exe:
        return 0.0
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW,
        ).stdout.strip()
        d = float(out.splitlines()[0]) if out else 0.0
        return d if d > 0 else 0.0
    except Exception as e:
        log.debug("ffprobe failed for %s: %s", path, e)
        return 0.0


_vlc_instance = None


def probe_with_vlc(path: str, timeout: float = 8.0) -> float:
    """libvlc metadata parse. Slower; call from a background thread only."""
    global _vlc_instance
    try:
        import vlc  # type: ignore
        if _vlc_instance is None:
            _vlc_instance = vlc.Instance("--quiet", "--no-video", "--no-audio")
        media = _vlc_instance.media_new(path)
        try:
            media.parse_with_options(vlc.MediaParseFlag.local, int(timeout * 1000))
            end = time.time() + timeout
            done = (vlc.MediaParsedStatus.done, vlc.MediaParsedStatus.failed,
                    vlc.MediaParsedStatus.timeout, vlc.MediaParsedStatus.skipped)
            while time.time() < end and media.get_parsed_status() not in done:
                time.sleep(0.05)
        except AttributeError:      # old python-vlc: no parse_with_options
            media.parse()
        ms = media.get_duration()
        media.release()
        return ms / 1000.0 if ms and ms > 0 else 0.0
    except Exception as e:
        log.debug("libvlc probe failed for %s: %s", path, e)
        return 0.0


def probe_duration_seconds(path: str, allow_vlc: bool = True) -> float:
    """Best-known duration of `path` in seconds (0.0 = nothing trustworthy)."""
    if not path or not os.path.exists(path):
        return 0.0
    try:
        size = os.path.getsize(path)
    except OSError:
        return 0.0

    info = probe_video(path)
    if info and info.duration >= MIN_SANE_DURATION and plausible(info.duration, size):
        log.debug("%s: %s -> %.1fs (container)", os.path.basename(path), info.source, info.duration)
        return info.duration

    d = probe_with_ffprobe(path)
    if d >= MIN_SANE_DURATION and plausible(d, size):
        log.debug("%s: ffprobe -> %.1fs", os.path.basename(path), d)
        return d

    # Before libvlc: it claims 37 h for at least one file in this catalog.
    hint = duration_hint(path)
    if hint >= MIN_SANE_DURATION and plausible(hint, size):
        log.debug("%s: filename hint -> %.1fs", os.path.basename(path), hint)
        return hint

    if allow_vlc:
        d = probe_with_vlc(path)
        if d >= MIN_SANE_DURATION:
            if plausible(d, size):
                log.debug("%s: libvlc -> %.1fs", os.path.basename(path), d)
                return d
            log.info("%s: libvlc reported %.0fs, rejected as implausible for %.0f MB "
                     "(broken timestamps?)", os.path.basename(path), d, size / 1e6)
    return 0.0


def probe_channel(state, channel, allow_vlc: bool = False) -> int:
    """Probe every unlocked video of one channel — programmes *and* commercials.
    Returns how many were newly locked.

    v0.7.0: ads are probed too. The broadcast timeline has to know how long a
    commercial is (it sits between two programmes at a fixed wall-clock time),
    and a 0 there used to mean "assume 30 s", which drifts the whole schedule.
    `allow_vlc=False` keeps this safe to call on the UI thread (the container
    probe is pure file I/O).
    """
    n = 0
    for v in list(channel.videos):
        if state.is_locked(channel.id, v.id):
            continue
        d = probe_duration_seconds(v.src, allow_vlc=allow_vlc)
        if d >= state.MIN_DURATION:
            state.set_duration(channel.id, v.id, d, source="probe")
            n += 1
    # Commercials: same probe order as programmes (container → ffprobe →
    # filename hint → libvlc).  v0.7.6: the VLC fallback is allowed again here —
    # a 12-second ad with no known length makes the timeline assume 30 s, so the
    # player cannot seek into it, restarts it from 0 and the pod drifts.  The
    # probe runs on the startup thread and the results are locked, so this cost
    # is paid once.
    for v in list(channel.commercials):
        if state.is_locked(channel.id, v.id):
            continue
        d = probe_duration_seconds(v.src, allow_vlc=allow_vlc)
        if d >= state.MIN_DURATION:
            state.set_duration(channel.id, v.id, d, source="probe")
            n += 1
    return n


def start_background_probe(state, catalog, save_cb=None) -> threading.Thread:
    """Probe every channel's videos on a daemon thread."""
    def run():
        total = 0
        for ch in catalog.channels:
            try:
                total += probe_channel(state, ch, allow_vlc=True)
            except Exception as e:      # never let probing crash the app
                log.warning("probe of %s failed: %s", ch.id, e)
        log.info("Duration probe finished: %d video length(s) locked", total)
        if save_cb:
            try:
                save_cb()
            except Exception:
                pass

    t = threading.Thread(target=run, name="duration-probe", daemon=True)
    t.start()
    return t
