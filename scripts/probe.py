"""
probe.py — read a video's real duration/size straight from its container (no ffprobe)

Why this exists
---------------
The live-TV schedule needs every video's length, but the machine this project
runs on has no ffprobe, and libvlc reports a *wrong* length for at least one
MPEG-PS recording (37 h for a 44-minute file).  Learning that number poisons
schedule_state.json and makes the channel join the wrong video.

This module reads just enough of the container header to answer:

    duration of  mp4 / mov / m4v / mkv / avi / mpg / mpeg
    pixel size of mp4 / mkv

No third-party dependencies, no subprocesses — it reads a few hundred KB per
file instead of decoding anything.  Every value is sanity-checked against the
file size (`plausible()`), because MPEG-PS files whose timestamps are broken
will happily report 26 hours for a 44-minute recording.

Public API
----------
    probe_video(path) -> VideoInfo | None       duration / width / height / source
    duration_hint(name) -> float                 parse "44′40" / "1h02m33s" style names
    plausible(duration, size_bytes) -> bool      bitrate sanity check
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass
from typing import Optional

# Bitrate window used to reject impossible durations. A 720x480 recording sits
# between roughly 300 kbit/s (very compressed) and 15 Mbit/s (MPEG-2 capture);
# the window is deliberately wide so only nonsense is filtered out.
MIN_BITRATE = 120_000        # bit/s
MAX_BITRATE = 40_000_000     # bit/s
MAX_DURATION = 24 * 3600.0   # nothing in this catalog is longer than a day

_SAMPLE_ENTRY_TYPES = (b"avc1", b"avc3", b"hvc1", b"hev1", b"mp4v", b"av01", b"vp09", b"vp08")


@dataclass
class VideoInfo:
    duration: float = 0.0          # seconds; 0 = unknown
    width: int = 0
    height: int = 0
    source: str = ""               # which parser produced `duration`

    @property
    def dims(self) -> tuple[int, int]:
        return (self.width, self.height)


# ── raw byte helpers ─────────────────────────────────────────────────────────

def _read_window(path: str, size: int, nbytes: int, from_end: bool) -> bytes:
    with open(path, "rb") as f:
        if from_end:
            f.seek(max(0, size - nbytes))
        return f.read(nbytes)


def _windows(path: str, size: int) -> list[bytes]:
    """Head + escalating tail windows.  `moov` of a 3 GB MP4 can be several MB,
    so start small (fast) and grow only if the box wasn't found."""
    out = [_read_window(path, size, 512 * 1024, False)]
    for n in (512 * 1024, 4 * 1024 * 1024, 16 * 1024 * 1024):
        if n < size:
            out.append(_read_window(path, size, n, True))
    return out


def plausible(duration: float, size_bytes: float) -> bool:
    """True when `duration` is consistent with the file size (bitrate window)."""
    if not duration or duration <= 0 or size_bytes <= 0:
        return False
    if duration > MAX_DURATION:
        return False
    bitrate = size_bytes * 8.0 / duration
    return MIN_BITRATE <= bitrate <= MAX_BITRATE


# ── MP4 / MOV ────────────────────────────────────────────────────────────────

def _mp4_from_buffer(buf: bytes, info: VideoInfo) -> None:
    """Pull mvhd (duration) and the first video sample entry (dimensions)."""
    if not info.duration:
        i = buf.find(b"mvhd")
        while i >= 0:
            try:
                body = i + 4
                ver = buf[body]
                if ver == 0:
                    timescale, dur = struct.unpack(">II", buf[body + 12:body + 20])
                else:
                    timescale, dur = struct.unpack(">IQ", buf[body + 20:body + 32])
                if timescale:
                    info.duration = dur / float(timescale)
                    info.source = "mp4/mvhd"
                    break
            except (struct.error, IndexError):
                pass
            i = buf.find(b"mvhd", i + 4)

    if not info.width:
        for magic in _SAMPLE_ENTRY_TYPES:
            i = buf.find(magic)
            if i < 0:
                continue
            try:
                w, h = struct.unpack(">HH", buf[i + 28:i + 32])
            except struct.error:
                continue
            if 0 < w < 8192 and 0 < h < 8192:
                info.width, info.height = w, h
                break

    if not info.width:
        # tkhd width/height are 16.16 fixed point
        i = buf.find(b"tkhd")
        if i >= 0:
            try:
                body = i + 4
                ver = buf[body]
                off = body + (76 if ver == 0 else 88)
                w, h = struct.unpack(">II", buf[off:off + 8])
                if w and h and w % 65536 == 0 and h % 65536 == 0:
                    info.width, info.height = w // 65536, h // 65536
            except (struct.error, IndexError):
                pass


# ── AVI (RIFF) ───────────────────────────────────────────────────────────────

def _avi(buf: bytes, info: VideoInfo, size: int = 0) -> None:
    i = buf.find(b"avih")
    if i < 0:
        return
    # 'avih' is followed by a 4-byte chunk size, then the struct.  Some muxers
    # (and hand-built files) omit the chunk size, so try both offsets.
    for skip in (8, 4):
        base = i + skip
        try:
            usec_per_frame = struct.unpack("<I", buf[base:base + 4])[0]
            total_frames = struct.unpack("<I", buf[base + 16:base + 20])[0]
        except struct.error:
            continue
        if not usec_per_frame or not total_frames:
            continue
        duration = usec_per_frame * total_frames / 1e6
        if size and not plausible(duration, size):
            continue
        info.duration = duration
        info.source = "avi/avih"
        return


# ── MPEG program stream ──────────────────────────────────────────────────────

def _pts_list(buf: bytes) -> list[int]:
    """Collect PTS values from MPEG-2 PES headers (33-bit, 90 kHz)."""
    out = []
    i, n = 0, len(buf) - 20
    while i < n:
        if buf[i] == 0 and buf[i + 1] == 0 and buf[i + 2] == 1:
            c = buf[i + 3]
            if 0xC0 <= c <= 0xEF or 0xBD <= c <= 0xBF:       # audio / video / private
                if (buf[i + 6] & 0xC0) == 0x80 and (buf[i + 7] & 0x80):
                    p = buf[i + 9:i + 14]        # PTS follows the 3-byte PES flags block
                    pts = (((p[0] >> 1) & 0x07) << 30) | (p[1] << 22) | \
                          (((p[2] >> 1) & 0x7F) << 15) | (p[3] << 7) | ((p[4] >> 1) & 0x7F)
                    out.append(pts)
        i += 1
    return out


def _mpeg_ps(head: bytes, tail: bytes, size: int, info: VideoInfo) -> bool:
    """Returns True when PTS values were found (even if the span was rejected)."""
    hp, tp = _pts_list(head), _pts_list(tail)
    if not hp or not tp:
        return False
    span = (tp[-1] - hp[0]) % (1 << 33) / 90000.0
    if plausible(span, size):
        info.duration = span
        info.source = "mpeg-ps/pts"
        return True
    # The timestamps wrap or jump around (broken capture).  Try the widest
    # consistent span instead: every delta seen in the tail, largest plausible.
    first = hp[0]
    best = 0.0
    for pts in tp:
        d = (pts - first) % (1 << 33) / 90000.0
        if plausible(d, size) and d > best:
            best = d
    if best:
        info.duration = best
        info.source = "mpeg-ps/pts~"
    return True


# ── Matroska ─────────────────────────────────────────────────────────────────

def _ebml_vint(buf: bytes, i: int, keep_marker: bool) -> tuple[int, int]:
    """Return (value, bytes_used) for an EBML variable-length integer."""
    first = buf[i]
    length = 1
    mask = 0x80
    while length <= 8 and not (first & mask):
        mask >>= 1
        length += 1
    if length > 8 or i + length > len(buf):
        raise ValueError("bad vint")
    value = first if keep_marker else first & (mask - 1)
    for k in range(1, length):
        value = (value << 8) | buf[i + k]
    return value, length


def _mkv(buf: bytes, info: VideoInfo) -> None:
    """Walk EBML down to Segment > Info and read Duration + TimecodeScale."""
    i = 0
    scale = 1_000_000            # ns per tick (Matroska default)
    duration_ticks = 0.0
    while i < len(buf) - 2:
        try:
            eid, n1 = _ebml_vint(buf, i, True)
            size, n2 = _ebml_vint(buf, i + n1, False)
        except (ValueError, IndexError):
            return
        body = i + n1 + n2
        if size == 0xFFFFFFFFFFFFFF:      # unknown size — descend anyway
            size = len(buf) - body
        if eid == 0x18538067 or eid == 0x1549A966:   # Segment | Info
            i = body
            continue
        if eid == 0x2AD7B1 and size <= 8:            # TimecodeScale
            scale = int.from_bytes(buf[body:body + size], "big") or scale
        elif eid == 0x4489 and size in (4, 8):       # Duration (float)
            duration_ticks = (struct.unpack(">f", buf[body:body + 4])[0] if size == 4
                              else struct.unpack(">d", buf[body:body + 8])[0])
            break
        i = body + size

    if duration_ticks:
        info.duration = duration_ticks * scale / 1e9
        info.source = "mkv/info"


# ── public entry point ───────────────────────────────────────────────────────

_EXT_PARSER = {
    ".mp4": "mp4", ".m4v": "mp4", ".mov": "mp4",
    ".mkv": "mkv", ".webm": "mkv",
    ".avi": "avi",
    ".mpg": "ps", ".mpeg": "ps",
}


def probe_video(path: str) -> Optional[VideoInfo]:
    """Container-only probe. Returns None for unknown extensions or unreadable files."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size <= 0:
        return None
    kind = _EXT_PARSER.get(os.path.splitext(path)[1].lower())
    if not kind:
        return None

    info = VideoInfo()
    try:
        if kind == "mp4":
            for buf in _windows(path, size):
                _mp4_from_buffer(buf, info)
                if info.duration and info.width:
                    break
        elif kind == "avi":
            _avi(_read_window(path, size, 256 * 1024, False), info, size)
        elif kind == "mkv":
            _mkv(_read_window(path, size, 1024 * 1024, False), info)
        elif kind == "ps":
            head = _read_window(path, size, min(4 * 1024 * 1024,
                                                max(64 * 1024, size // 2)), False)
            # Tail window escalates: captures often end with padding/garbage,
            # so the last PES header may sit well before EOF.
            for tail_n in (4 * 1024 * 1024, 32 * 1024 * 1024, 128 * 1024 * 1024):
                if info.duration:
                    break
                tail = _read_window(path, size, min(tail_n, size), True)
                if _mpeg_ps(head, tail, size, info):
                    break
    except Exception:                     # a malformed header must never crash the app
        return info if (info.duration or info.width) else None

    if info.duration and not plausible(info.duration, size):
        info.duration = 0.0
        info.source = "rejected"
    return info


# ── filename hints ───────────────────────────────────────────────────────────

_HINT_PATTERNS = [
    # 44′40  /  44'40   (Japanese TV convention: minute-prime + seconds)
    (re.compile(r"(?<!\d)(\d{1,3})\s*[′']\s*(\d{1,2})(?!\d)"), "m_s"),
    # 44分40秒 / 44分
    (re.compile(r"(\d{1,3})\s*分\s*(?:(\d{1,2})\s*秒)?"), "m_s"),
    # 1h02m33s / 1h02m  (explicit hours)
    (re.compile(r"(?<!\d)(\d{1,2})\s*h\s*(\d{1,3})\s*m(?:in)?\s*(?:(\d{1,2})\s*s)?", re.I), "h_m_s"),
    # 01:02:33
    (re.compile(r"(?<!\d)(\d{1,2}):(\d{2}):(\d{2})(?!\d)"), "h_m_s"),
    # 25m30s / 25min / 25m  (no hours)
    (re.compile(r"(?<!\d)(\d{1,3})\s*m(?:in)?\s*(?:(\d{1,2})\s*s)?", re.I), "m_s_opt"),
]


def duration_hint(name: str) -> float:
    """Read a duration out of a filename, e.g. '… (150) 44′40 ハロモニ…' -> 2680 s.

    Returns 0.0 when the name carries no usable hint.  Episode numbers in
    parentheses are deliberately ignored (they are not durations).
    """
    stem = os.path.splitext(os.path.basename(name))[0]
    for pattern, kind in _HINT_PATTERNS:
        for m in pattern.finditer(stem):
            groups = [g for g in m.groups() if g is not None]
            try:
                if kind in ("m_s", "m_s_opt"):
                    minutes = int(groups[0])
                    seconds = int(groups[1]) if len(groups) > 1 else 0
                    total = minutes * 60 + seconds
                else:                       # h_m_s
                    if len(groups) == 3:
                        total = int(groups[0] or 0) * 3600 + int(groups[1]) * 60 + int(groups[2])
                    else:
                        total = int(groups[0] or 0) * 3600 + int(groups[1]) * 60
            except (ValueError, IndexError):
                continue
            if total >= 30:                  # shorter than 30 s is almost certainly not a duration
                return float(total)
    return 0.0


# ── CLI ──────────────────────────────────────────────────────────────────────

def _fmt(seconds: float) -> str:
    if not seconds:
        return "?"
    h, rem = divmod(int(round(seconds)), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


if __name__ == "__main__":
    import sys
    targets = sys.argv[1:]
    if not targets:
        print("usage: python scripts/probe.py <file-or-folder> [...]")
        raise SystemExit(2)
    files: list[str] = []
    for t in targets:
        if os.path.isdir(t):
            for name in sorted(os.listdir(t)):
                p = os.path.join(t, name)
                if os.path.isfile(p) and os.path.splitext(name)[1].lower() in _EXT_PARSER:
                    files.append(p)
        else:
            files.append(t)
    print(f"{'duration':>10}  {'size':>9}  {'dims':>10}  {'source':<14}  file")
    for p in files:
        info = probe_video(p) or VideoInfo()
        size = os.path.getsize(p)
        hint = duration_hint(p)
        dur = info.duration or hint
        src = info.source if info.duration else ("filename" if hint else "?")
        dims = f"{info.width}x{info.height}" if info.width else "-"
        print(f"{_fmt(dur):>10}  {size / 1e6:8.1f}M  {dims:>10}  {src:<14}  {os.path.basename(p)}")
