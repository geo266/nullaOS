"""test_probe.py — regression tests for the container probe (no Qt, no VLC, no ffmpeg).

Run:  python scripts/test_probe.py
      (or: python -m unittest scripts.test_probe -v)

Everything is built in a temp folder, so the tests don't need the real catalog.
"""

from __future__ import annotations

import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.probe import (  # noqa: E402
    duration_hint, plausible, probe_video, MAX_DURATION,
)


# ── synthetic containers ─────────────────────────────────────────────────────

def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + kind + payload


def _mvhd(timescale: int, duration: int) -> bytes:
    payload = (b"\x00\x00\x00\x00"                  # version 0 + flags
               + struct.pack(">II", 0, 0)           # creation / modification
               + struct.pack(">II", timescale, duration)
               + b"\x00" * 80)
    return _box(b"mvhd", payload)


def _tkhd(width: int, height: int) -> bytes:
    payload = (b"\x00\x00\x00\x00"
               + struct.pack(">II", 0, 0)
               + struct.pack(">I", 1) + struct.pack(">I", 0)
               + struct.pack(">I", 0) + b"\x00" * 8
               + struct.pack(">HHHH", 0, 0, 0, 0)
               + b"\x00" * 36
               + struct.pack(">II", width << 16, height << 16))
    return _box(b"tkhd", payload)


def _stsd(width: int, height: int) -> bytes:
    entry = (b"\x00" * 6 + struct.pack(">H", 1)
             + struct.pack(">HH", 0, 0) + b"\x00" * 12
             + struct.pack(">HH", width, height))
    return _box(b"stsd", b"\x00\x00\x00\x00" + struct.pack(">I", 1) + _box(b"avc1", entry))


def make_mp4(path: str, timescale: int, duration: int, w: int, h: int, pad_to: int = 0) -> None:
    moov = _box(b"moov", _mvhd(timescale, duration)
                + _box(b"trak", _tkhd(w, h) + _box(b"mdia", _stsd(w, h))))
    with open(path, "wb") as f:
        f.write(_box(b"ftyp", b"isom" + b"\x00\x00\x02\x00" + b"isomiso2"))
        f.write(moov)
        f.write(_box(b"mdat", b"\x00" * 4096))
    if pad_to:
        os.truncate(path, pad_to)      # sparse: sets a realistic file size without writing GBs


def make_avi(path: str, usec_per_frame: int, frames: int, pad_to: int = 0) -> None:
    avih = struct.pack("<IIII", usec_per_frame, 0, 0, 0) + struct.pack("<I", frames)
    avih = avih.ljust(56, b"\x00")
    body = b"AVI " + _box(b"LIST", b"hdrl" + _box(b"avih", avih))
    data = body + b"movi" + struct.pack("<I", 0) + b"\x00" * 2048
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(data)) + data)
    if pad_to:
        os.truncate(path, pad_to)


def _pes(stream_id: int, pts: int) -> bytes:
    """A minimal MPEG-2 PES packet carrying a PTS (canonical 33-bit encoding)."""
    p = bytes([
        ((pts >> 30) & 0x07) << 1 | 0x01,
        (pts >> 22) & 0xFF,
        (((pts >> 15) & 0x7F) << 1) | 0x01,
        (pts >> 7) & 0xFF,
        ((pts & 0x7F) << 1) | 0x01,
    ])
    payload = bytes([0x80, 0x80, 0x05]) + p + b"\x00" * 64
    return (b"\x00\x00\x01" + bytes([stream_id])
            + struct.pack(">H", len(payload)) + payload)


def make_mpeg_ps(path: str, start_s: float, seconds: float, media_bytes: int = 19_000_000) -> None:
    """Real PTS at the head and tail, media bytes in between (like a capture)."""
    head = _pes(0xE0, int(start_s * 90000)) + _pes(0xC0, int(start_s * 90000))
    tail = _pes(0xE0, int((start_s + seconds) * 90000))
    with open(path, "wb") as f:
        f.write(head)
        block = b"\x00" * (1024 * 1024)
        for _ in range(media_bytes // len(block)):
            f.write(block)
        f.write(tail)


# ── tests ────────────────────────────────────────────────────────────────────

class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    # mp4 ---------------------------------------------------------------
    def test_mp4_duration_and_dims(self):
        p = self.path("clip.mp4")
        make_mp4(p, timescale=1000, duration=1721067, w=640, h=480, pad_to=40_000_000)
        info = probe_video(p)
        self.assertIsNotNone(info)
        self.assertAlmostEqual(info.duration, 1721.067, places=3)
        self.assertEqual(info.dims, (640, 480))
        self.assertTrue(info.source.startswith("mp4"))

    def test_mp4_64bit_mvhd(self):
        p = self.path("v1.mp4")
        payload = (b"\x01\x00\x00\x00"
                   + struct.pack(">QQ", 0, 0)
                   + struct.pack(">I", 90000)
                   + struct.pack(">Q", 90000 * 90)
                   + b"\x00" * 80)
        with open(p, "wb") as f:
            f.write(_box(b"ftyp", b"isom" + b"\x00" * 8))
            f.write(_box(b"moov", _box(b"mvhd", payload)))
            f.write(_box(b"mdat", b"\x00" * 8192))
        os.truncate(p, 40_000_000)
        info = probe_video(p)
        self.assertAlmostEqual(info.duration, 90.0, places=3)

    def test_mp4_absurd_duration_rejected(self):
        """A 1.2 GB file claiming 37 hours is a broken timeline, not a long film."""
        p = self.path("broken.mp4")
        make_mp4(p, timescale=1000, duration=134_013_535, w=640, h=480)
        with open(p, "ab") as f:
            f.write(b"\x00" * (12 * 1024 * 1024))       # ~12 MB -> 65 kbit/s for 37 h
        info = probe_video(p)
        self.assertEqual(info.duration, 0.0)
        self.assertEqual(info.source, "rejected")

    # avi ---------------------------------------------------------------
    def test_avi_duration(self):
        p = self.path("ep.avi")
        make_avi(p, usec_per_frame=40000, frames=93527, pad_to=80_000_000)   # 25 fps, 3741.08 s
        info = probe_video(p)
        self.assertAlmostEqual(info.duration, 3741.08, places=2)

    # mpeg-ps -----------------------------------------------------------
    def test_mpeg_ps_span(self):
        p = self.path("capture.mpg")
        make_mpeg_ps(p, start_s=73866.0, seconds=300.0)
        info = probe_video(p)
        self.assertAlmostEqual(info.duration, 300.0, delta=2.0)
        self.assertTrue(info.source.startswith("mpeg-ps"))

    # filename hints ------------------------------------------------------
    def test_hint_prime_seconds(self):
        self.assertAlmostEqual(duration_hint("030309 ハロモニ。 (150) 44′40 ハロモニ。"), 2680)
        self.assertAlmostEqual(duration_hint("030323 ハロモニ。 (152) 44'40 VS"), 2680)

    def test_hint_other_forms(self):
        self.assertAlmostEqual(duration_hint("show 1h02m33s.mp4"), 3753)
        self.assertAlmostEqual(duration_hint("番組 44分40秒.mpg"), 2680)
        self.assertAlmostEqual(duration_hint("rec 01:02:33.mkv"), 3753)
        self.assertAlmostEqual(duration_hint("clip 25m30s.mp4"), 1530)

    def test_hint_ignores_episode_numbers_and_dates(self):
        for name in ("GAME BREAK(ゲームブレイク) 2003年01月08日-r8O1UKtKrRY.mp4",
                     "Love generation_EP01.avi",
                     "Arisa Good Luck DVD.mp4",
                     "TV (150) episode.mp4"):
            self.assertEqual(duration_hint(name), 0.0, name)

    # plausibility ---------------------------------------------------------
    def test_plausible(self):
        self.assertTrue(plausible(2680, 1_224_000_000))
        self.assertTrue(plausible(14862, 3_000_000_000))
        self.assertFalse(plausible(134_013, 1_224_000_000))
        self.assertFalse(plausible(0, 1000))
        self.assertFalse(plausible(MAX_DURATION + 1, 10 ** 12))

    def test_unknown_extension(self):
        p = self.path("x.flv")
        with open(p, "wb") as f:
            f.write(b"\x00" * 1024)
        self.assertIsNone(probe_video(p))

    def test_missing_file(self):
        self.assertIsNone(probe_video(self.path("nope.mp4")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
