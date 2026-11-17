"""Render the README screenshots offscreen, from a synthetic catalog.

    python tools/shots.py

Writes docs/img/banner.png and docs/img/guide.png.  Everything on screen comes
from a throwaway temp catalog with invented channel and programme names, so no
real capture titles, blurbs or folders end up in the repository.
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)


class _E:
    MediaPlayerPlaying = 0
    MediaPlayerPaused = 1
    MediaPlayerEndReached = 2
    MediaPlayerEncounteredError = 3
    MediaPlayerLengthChanged = 4


class _Dummy:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


vlc = types.ModuleType("vlc")
vlc.Instance = _Dummy
vlc.MediaParseFlag = _Dummy()
vlc.MediaParsedStatus = _Dummy()
vlc.EventType = _E
vlc.VideoMarqueeOption = _Dummy()
sys.modules["vlc"] = vlc

from PySide6.QtCore import QPoint, Qt, QRectF                      # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap       # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

from scripts.screens.base import load_fonts                       # noqa: E402
from scripts.app import MainWindow                                # noqa: E402

W, H = 720, 480


class FakePlayer:
    def __init__(self):
        self.time_s = 0.0
        self.length_s = 2679.84
        self.position = 0.42
        self.src = ""
        self.playing = True

    def play_item(self, src, deinterlace="none", aspect="", crop=""):
        self.src = src

    def get_time_ms(self):
        return int(self.time_s * 1000)

    def current_length_ms(self):
        return int(self.length_s * 1000)

    def current_position(self):
        return self.position

    def current_src(self):
        return self.src

    def seek_to(self, frac):
        self.position = frac

    def set_volume(self, v):
        pass

    def set_aspect(self, a):
        pass

    def set_crop(self, c):
        pass

    def pause(self):
        self.playing = False

    def resume(self):
        self.playing = True

    def stop(self):
        self.playing = False

    def release(self):
        pass


def make_catalog(tmp: Path) -> Path:
    """Three channels, invented names, real-looking structure."""
    def channel(name, titles, blurbs=(), ads=6, logo=False):
        ch = tmp / name
        (ch / "Commercials").mkdir(parents=True)
        for title in titles:
            (ch / f"{title}.mpg").write_bytes(b"\x00" * 4096)
        for title, blurb in zip(titles, blurbs):
            (ch / f"{title}.txt").write_text(blurb, encoding="utf-8")
        for i in range(ads):
            (ch / "Commercials" / f"spot {i + 1:02d}.mpg").write_bytes(b"\x00" * 2048)
        if logo:
            (ch / "Logos").mkdir()
        return ch

    channel("MOVIE WAVE", ["Night Drive", "Harbour Lights", "The Long Weekend"],
            ["A courier spends one rain-soaked night returning a package nobody "
             "ordered.",
             "Two night-shift radio hosts fall for a caller they never meet.",
             "Three friends, one borrowed car and a very long weekend."])
    channel("RETRO ONE", ["Test Card Hour", "Cartoon Block A"],
            ["Colour bars, a tone and the national anthem at sign-off.",
             "Six shorts, one intermission and no plot whatsoever."])
    channel("JP TV", ["Midnight Variety ep12", "Kissa Corner ep03"],
            ["The panel guesses the fourth member of a comedy troupe.",
             "A late-night café, two regulars and a very slow conversation."])
    return tmp


def bars(w=W, h=H) -> QPixmap:
    """SMPTE-ish colour bars, so the banner is judged over real picture."""
    pm = QPixmap(w, h)
    p = QPainter(pm)
    cols = ["#C0C0C0", "#C0C000", "#00C0C0", "#00C000",
            "#C000C0", "#C00000", "#0000C0", "#101010"]
    for i, c in enumerate(cols):
        p.fillRect(QRectF(i * w / 8, 0, w / 8 + 1, h * 0.70), QColor(c))
    p.fillRect(QRectF(0, h * 0.70, w, h * 0.30), QColor("#E8E8E8"))
    p.end()
    return pm


def canvas() -> tuple[QImage, QPainter]:
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(Qt.black)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    return img, p


def main() -> int:
    app = QApplication(sys.argv)
    load_fonts()
    tmp = Path(tempfile.mkdtemp(prefix="nulla-shots-"))
    make_catalog(tmp)
    sys.argv = [sys.argv[0], "--catalog", str(tmp)]

    win = MainWindow()
    win.show()
    app.processEvents()
    win.mode = "tv"
    win._tune_start_timer.stop()
    win.player = FakePlayer()

    # ── 1. boot screen ────────────────────────────────────────────────────
    win.show_boot()
    app.processEvents()
    img, p = canvas()
    win.boot_screen.resize(W, H)
    win.boot_screen.render(p, QPoint(0, 0))
    p.end()
    img.save(str(OUT / "boot.png"))

    # ── 2. live + channel banner ──────────────────────────────────────────
    win.mode = "tv"
    win.tune_to_channel(1)
    win._start_pending_tune()
    app.processEvents()
    win._release_snow()
    live = win.live_screen
    live._tuning_hold = False
    live._tuning_alpha = 0.0
    live._tuning_timer.stop()
    live.current_position = 0.42
    live.show_banner()
    for _ in range(30):              # let the fade finish
        live._tick_banner()
    img, p = canvas()
    p.drawPixmap(0, 0, bars())
    p.setRenderHint(QPainter.Antialiasing, True)
    live.paint_overlay(p, W, H)
    p.end()
    img.save(str(OUT / "banner.png"))

    # ── 3. guide ──────────────────────────────────────────────────────────
    win.show_guide()
    app.processEvents()
    guide = win.guide_screen
    guide.resize(W, H)
    img, p = canvas()
    guide.render(p, QPoint(0, 0))
    # The live preview panel is a real VLC child window; with no libvlc here it
    # renders black, which looks like a bug in a still.  Put a frame in it so
    # the screenshot shows what the panel is for.
    p.setRenderHint(QPainter.Antialiasing, False)
    p.drawPixmap(guide.PREVIEW_X + 3, guide.PREVIEW_Y + 3,
                 bars(guide.PREVIEW_W - 6, guide.PREVIEW_CAPTION_TOP))
    p.end()
    img.save(str(OUT / "guide.png"))

    for name in ("banner", "guide"):
        print("wrote", OUT / f"{name}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
