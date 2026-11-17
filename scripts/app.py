"""
app.py — nullaOS main application (PySide6 + python-vlc + pygame gamepad)

Architecture:
  - MainWindow owns:
      - Catalog (channels + library)
      - InputController (keyboard + gamepad unified action stream)
      - VlcPlayer (created lazily on first playback)
      - QStackedWidget with screens: Boot, Live, Guide, Browser
  - InputController.action_emitted signal -> MainWindow._dispatch_action
  - _dispatch_action routes to current screen's handle_input(action)
  - Each screen implements handle_input() to react to up/down/left/right/
    enter/back/play_pause/guide/menu/info/vault/quit

User spec implemented here:
  - Up/Down switches channels (live) AND browses TV guide (when guide is open)
  - Enter selects, Backspace exits guide, Spacebar pauses/resumes
  - Gamepad also supported via pygame polling
  - TV mode (channel surf + per-channel commercial injection)
  - Browser mode (media explorer — library on-demand, no commercials)
  - Per-channel commercials: Japanese channel uses Japanese ads only,
    USA channels use USA ads only (strict per-channel pools)

Run on Windows 11:
  pip install -r requirements.txt
  python scripts/app.py

CUSTOMIZATION POINTS:
  - APP_NAME / APP_VERSION (line ~50)
  - Window resolution (line ~130) — set to 720x480 for the Aiwa CRT
"""

from __future__ import annotations

import sys
import os
import time
import json
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QObject, Signal, QTimer, QPoint
from PySide6.QtGui import QFontDatabase, QKeyEvent, QPalette, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QStackedWidget, QSizePolicy,
)

# Ensure scripts/ is on sys.path so relative imports work even when run as
# `python scripts/app.py`
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR.parent))

from scripts.catalog import (
    Catalog, Channel, VideoItem, load_catalog, find_channel_by_number,
    scan_real_folder, DAYPART_FOLDERS,
)  # noqa: E402
from scripts.playlist import PlayItem  # noqa: E402
from scripts.vlc_player import VlcPlayer  # noqa: E402
from scripts.input import InputController  # noqa: E402
from scripts.schedule_state import ScheduleState  # noqa: E402
from scripts import window_state  # noqa: E402
from scripts.cover_wait import CoverWait, RELEASE, GIVE_UP  # noqa: E402
from scripts.settings import Settings  # noqa: E402
from scripts.clock import AppClock  # noqa: E402
from scripts.timeline import (  # noqa: E402
    AdPolicy, Airing, ChannelTimeline, policy_for_channel,
)
from scripts.display import DisplayOverrides, PRESET_LABELS, CROP_LABELS  # noqa: E402
from scripts.duration_probe import probe_channel, start_background_probe, probe_duration_seconds  # noqa: E402
from scripts.probe import plausible  # noqa: E402
from scripts.overlay import VideoOverlay  # noqa: E402
from scripts.screens.base import load_fonts  # noqa: E402
from scripts.screens.boot import BootScreen  # noqa: E402
from scripts.screens.live import LiveScreen  # noqa: E402
from scripts.screens.guide import GuideScreen  # noqa: E402
from scripts.screens.browser import BrowserScreen  # noqa: E402
from scripts.screens.picker import PickerScreen  # noqa: E402
from scripts.screens.menu import MenuScreen  # noqa: E402
from scripts.screens.settings import SettingsScreen  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("nullaOS")

# ── Branding ────────────────────────────────────────────────────────────────
# The version lives in scripts/version.py. Bump APP_VERSION there for every
# variation — the window title and the boot-screen footer both read it.
from scripts.version import APP_NAME, APP_VERSION  # noqa: E402

# ── Commercial break policy ─────────────────────────────────────────────────
# v0.7.0: breaks are no longer injected by a timer — they are part of each
# channel's broadcast timeline (scripts/timeline.py), so the guide knows about
# them and changing channel during a break rejoins at the right place instead
# of skipping the rest of the pod.
#
# These are the *defaults*; every channel gets a deterministic ±2 min shift
# (AD_BREAK_JITTER_S) so two channels never break together, and
# catalog/<CHANNEL>/channel.json can override the interval and the pod size.
# NULLA_AD_BREAK_MINUTES overrides the default interval; 0 disables mid-rolls.
AD_BREAK_EVERY_S = float(os.environ.get("NULLA_AD_BREAK_MINUTES", "10")) * 60.0
AD_BREAK_MIN_VIDEO_S = 20 * 60      # only long videos get interrupted
AD_BREAK_TAIL_GUARD_S = 90          # ...and never this close to the end
# Commercials per break — used for BOTH kinds of break (mid-roll and between
# videos).  NULLA_AD_MIN / NULLA_AD_MAX override them without editing the file.
AD_BREAK_MIN_ADS = int(os.environ.get("NULLA_AD_MIN", "5"))
AD_BREAK_MAX_ADS = max(AD_BREAK_MIN_ADS, int(os.environ.get("NULLA_AD_MAX", "10")))
# After a break the video is reloaded and seeked back to where it stopped; for
# a moment VLC shows frame 0 of the file.  Hide that with a short black cover
# (False = use tuning snow instead).
RESUME_COVER_BLACK = True

# ── How long the picture may stay hidden while a channel settles ────────────
# The tuning / resume cover comes off when VLC is *really* showing the new
# media, not on a stopwatch.  v0.6.5: it used to be released after a flat 3.5 s
# (or as soon as get_time() was close), which a 1.2 GB MPEG-PS beats: the snow
# lifted while the vout still held the previous picture, so a stale frame sat
# on screen for about a second before playback started (seen on Kawaii TV).
COVER_MAX_S = 12.0          # absolute cap — then show whatever VLC has
COVER_FIRST_FRAME_S = 0.35  # no seek (joined at 0:00): the media must have played this much
COVER_CONFIRM_S = 0.08      # the clock must move this much between two polls
COVER_STALL_S = 1.5         # ...or this long without movement = it is frozen

# ── Per-channel ad policy (v0.7.0) ──────────────────────────────────────────
# The numbers above are the *defaults*.  Each channel shifts its interval by up
# to ±2 min (deterministic, from its id) so two channels never go to commercial
# at the same moment, and catalog/<CHANNEL>/channel.json can override it:
#     {"ad_every_min": 7, "ad_min": 2, "ad_max": 4}   (negative = no mid-rolls)
AD_BREAK_JITTER_S = 120.0

#: How far the guide can look ahead (the user asked for the 24–72 h window of
#: an early cable box: enough to be useful, not weeks of listings).
GUIDE_HORIZON_S = 72 * 3600


# ── Picture shape (v0.6.1) ──────────────────────────────────────────────────
# The user prefers 16:10 on the Aiwa: VLC crops the picture to 16:10 and then
# displays it at 16:10, so the tube shows edge-to-edge picture instead of
# 640x480 content sitting in black pillars. The thin letterbox bars that a
# 16:10 image leaves in a 3:2 window fall inside the CRT's overscan anyway.
VIDEO_ASPECT = "16:10"
VIDEO_CROP = "16:10"


class MainWindow(QMainWindow):
    """Main application window. Owns screens, input, player, and state."""

    #: How far the guide may look ahead (also read by GuideScreen).
    GUIDE_HORIZON_S = GUIDE_HORIZON_S

    def __init__(self):
        super().__init__()

        # ── State ──
        # v2: support `--catalog <path>` command-line arg for real-folder
        # scanning instead of the mock JSON. Usage:
        #   python scripts/app.py --catalog C:\Users\me\MyCatalog
        # Or just drop folders into nullaOS\catalog\ — the app will auto-use
        # that folder if it exists (no flag needed). Falls back to mock JSON
        # if neither is present.
        catalog_path = self._parse_catalog_arg()
        if not catalog_path:
            # No --catalog arg; check for project-local catalog/ folder
            project_root = Path(__file__).resolve().parent.parent
            local_catalog = project_root / "catalog"
            # v0.7.7: only auto-detect when there is at least one channel
            # folder.  A repository checkout ships `catalog/README.md`, and
            # treating that as a catalog made a fresh clone start with zero
            # channels instead of the mock/test-pattern fallback.
            if local_catalog.is_dir() and any(
                    p.is_dir() and not p.name.startswith(".")
                    for p in local_catalog.iterdir()):
                catalog_path = str(local_catalog)
                log.info(f"Auto-detected project-local catalog: {catalog_path}")
        if catalog_path:
            log.info(f"Loading real catalog from: {catalog_path}")
            self.catalog: Catalog = scan_real_folder(catalog_path)
        else:
            self.catalog = load_catalog()
        self.mode: str = "boot"  # "boot" | "tv" | "browser"
        self.current_channel: Optional[Channel] = None
        self.current_queue: list[PlayItem] = []
        self.current_idx: int = 0
        self.player: Optional[VlcPlayer] = None  # lazy-init on first playback
        self.volume: int = 80
        # ── Schedule state (MediaWave2000-style "always playing" TV) ──────
        # Each channel has a virtual playback position that advances in
        # real time even when you're not watching. When you tune in, you
        # join mid-stream. State persists across sessions via JSON.
        project_root = Path(__file__).resolve().parent.parent
        self._state_file = project_root / "schedule_state.json"
        self._schedule_state = ScheduleState.load(self._state_file)

        # ── Settings + clock (v0.7.0) ──────────────────────────────────────
        # One clock for the schedule, the guide and the OSD; the user can set it
        # VCR-style from the SETTINGS screen and the offset is remembered.
        self.settings = Settings.load(project_root / "settings.json")
        self.clock = AppClock(self.settings.get("clock_offset_s", 0.0),
                              on_change=self._on_clock_changed)
        self.volume = int(self.settings.get("volume", 80))
        # Per-file display aspect overrides (v0.7.1) — the escape hatch for the
        # handful of commercials whose source shape is not 16:10.
        self.display = DisplayOverrides.load(project_root / "display_overrides.json")

        # ── Broadcast timelines (v0.7.0) ───────────────────────────────────
        # One per channel: programmes + ad pods, wall-clock exact. Tuning, the
        # guide and its preview all read this instead of keeping their own
        # guesses (see timeline.py).
        self._timelines: dict[str, ChannelTimeline] = {}
        self._airing: Optional[Airing] = None
        # Pre-initialize state for all catalog channels so we know the
        # starting video for each (deterministic random based on channel id)
        for ch in self.catalog.channels:
            self._schedule_state.get_or_init(ch.id)        # Pending seek offset (set when tuning; applied once VLC loads the media)
        self._pending_seek_seconds: float = 0.0
        self._seek_target_s: float = 0.0        # where we want to be, in seconds
        self._seek_trusted_len: float = 0.0     # a duration we trust (container probe)
        self._seek_tries: int = 0
        self._seek_seeks: int = 0
        self._seek_last_issue: float = 0.0
        self._cover_wait: Optional[CoverWait] = None   # decides when the cover lifts
        self._cover_pending: bool = False      # a cover is waiting for a real picture
        self._snow_active: bool = False
        self._tune_muted: bool = False         # we turned the volume down for a tune
        # v0.7.0: the new media has actually started (MediaPlayerPlaying). Until
        # then the player's clock still belongs to the previous clip.
        self._media_started: bool = True
        self._media_started_at: float = 0.0
        self._media_requested_at: float = 0.0
        self._seek_poll_timer = QTimer(self)
        self._seek_poll_timer.setInterval(100)
        self._seek_poll_timer.timeout.connect(self._try_pending_seek)
        # The cover's absolute safety net.  v0.6.5: ONE restartable timer instead
        # of two QTimer.singleShot(4000) calls — a stale shot used to release the
        # *next* cover early (and with it, flash a frame).
        self._snow_guard = QTimer(self)
        self._snow_guard.setSingleShot(True)
        self._snow_guard.timeout.connect(self._release_snow)
        # Periodic save (every 2s) so state survives crashes / unexpected exits
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(2000)
        self._save_timer.timeout.connect(self._save_schedule_state)
        self._save_timer.start()

        # ── Channel-switch tuning transition (v0.5) ────────────────────────
        # The switch is covered by full-frame snow drawn by VideoOverlay, and
        # that snow is only released once the seek into the new video has
        # actually landed — so frame 0 of the new video can never flash on
        # screen (the old "shows the beginning, then jumps" bug).
        self._pending_tune: Optional[dict] = None  # holds the deferred tune
        self._tune_start_timer = QTimer(self)
        self._tune_start_timer.setSingleShot(True)
        self._tune_start_timer.setInterval(80)    # ms — let the snow paint first
        self._tune_start_timer.timeout.connect(self._start_pending_tune)

        # ── Live timeline tick (v0.7.0) ─────────────────────────────────────
        # The timeline decides what is airing; this timer only makes sure the
        # picture follows it.  It replaces the v0.6 mid-roll timer: ads are now
        # part of the schedule instead of being injected behind its back.
        self._live_tick_timer = QTimer(self)
        self._live_tick_timer.setInterval(1000)
        self._live_tick_timer.timeout.connect(self._live_tick)
        self._live_tick_timer.start()

        # v0.3.4: probe every video's REAL length up-front (ffprobe, then libvlc)
        # on a background thread. Probed lengths are locked in the schedule so
        # the live-TV positions stay stable (no jumps when lengths are learned).
        start_background_probe(
            self._schedule_state, self.catalog,
            save_cb=self._on_probe_finished,
        )

        # Failure tracking to prevent tight error loops when catalog files
        # don't exist on disk (the most common issue when the user runs
        # `python scripts/app.py` directly without first running
        # `python scripts/test_pattern.py` to generate SMPTE test patterns).
        self._missing_files_warned: set[str] = set()
        self._consecutive_failures: int = 0
        self._last_failure_time: float = 0.0
        self.catalog_playable_count: int = 0
        self.catalog_missing_count: int = 0

        # Pre-validate catalog — count how many files actually exist on disk.
        # Logs a friendly one-time warning if zero are found.
        self._validate_catalog()

        # ── Window setup ──
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setStyleSheet(f"QMainWindow {{ background-color: #0A0A12; }}")
        # Borderless fullscreen at CRT resolution.
        # ⚠ CUSTOMIZE: change to your CRT's actual resolution if different.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.resize(720, 480)

        # ── Window placement (v0.6.5) ──────────────────────────────────────
        # Borderless, so there is no title bar to grab: the window is dragged
        # from anywhere (see begin_window_drag / VideoOverlay) and its spot is
        # remembered per screen, so the CRT and the desktop monitor each keep
        # their own position.  window_state.py holds the rules.
        project_root = Path(__file__).resolve().parent.parent
        self._window_state_file = project_root / "window_state.json"
        self._drag_offset: Optional[QPoint] = None   # cursor − window origin
        self._restore_window_position()
        app = QGuiApplication.instance()
        if app is not None:
            # Unplugging the tube must not leave the window on a screen that is
            # gone (there is no title bar to drag it back with).
            app.screenAdded.connect(lambda *_: QTimer.singleShot(500, self._rescue_window_position))
            app.screenRemoved.connect(lambda *_: QTimer.singleShot(500, self._rescue_window_position))

        # ── Screens ──
        # Live screen needs a child video widget for VLC binding
        self.video_widget = QWidget()
        self.video_widget.setStyleSheet("background-color: black;")
        # NOTE: Removed setMinimumSize(720, 480) — it prevented the video
        # from shrinking to leave space for the bottom bar. The video can
        # now be any size, and _show_bar/_hide_bar control the geometry.
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.boot_screen = BootScreen(self)
        self.live_screen = LiveScreen(self, self.video_widget)
        self.guide_screen = GuideScreen(self)
        self.browser_screen = BrowserScreen(self)
        self.picker_screen = PickerScreen(self)
        self.menu_screen = MenuScreen(self)
        self.settings_screen = SettingsScreen(self)

        self.stack.addWidget(self.boot_screen)     # index 0
        self.stack.addWidget(self.live_screen)    # index 1
        self.stack.addWidget(self.guide_screen)   # index 2
        self.stack.addWidget(self.browser_screen) # index 3
        self.stack.addWidget(self.picker_screen) # index 4
        self.stack.addWidget(self.menu_screen)    # index 5
        self.stack.addWidget(self.settings_screen)  # index 6
        self._menu_return = None

        # ── Input ──
        self.input = InputController(parent=self,
                                     bindings=self.settings.get("hotkeys", {}) or {})
        self.input.action_emitted.connect(self._dispatch_action)

        # Show boot screen
        self._show_screen(self.boot_screen)

        # ── Video overlay (v0.5) ─────────────────────────────────────────────
        # A separate transparent, always-on-top window that sits exactly over
        # the video surface.  libvlc renders into its own child HWND, so this
        # is the only way to put the channel logo / progress bar / PAUSED text
        # on top of the picture on Windows. See overlay.py for the measurements.
        self.overlay = VideoOverlay(self)
        self.overlay.set_renderer(self.live_screen.paint_overlay)
        self.overlay.set_drag_target(self)      # v0.6.5: drag the window from the picture
        self.live_screen.overlay = self.overlay

    # ── Screen routing ────────────────────────────────────────────────────

    def _show_screen(self, screen: QWidget):
        self.stack.setCurrentWidget(screen)
        screen.setFocus()
        # The overlay only makes sense over the Live screen; hiding it
        # everywhere else also guarantees it can't cover the UI.
        if hasattr(self, "overlay"):
            self.overlay.set_active(screen is self.live_screen)
        if hasattr(screen, "on_show"):
            screen.on_show()

    def show_boot(self):
        self.mode = "boot"
        # Stop the player when going to boot — user doesn't want audio
        # continuing on the home screen. Schedule state is preserved
        # (it's wall-clock based, so it keeps advancing even with player stopped).
        if self.player:
            try:
                self.player.stop()
            except Exception:
                pass
        self._release_snow()
        self._airing = None
        self._show_screen(self.boot_screen)

    def show_live(self):
        self._show_screen(self.live_screen)

    def show_guide(self):
        self._show_screen(self.guide_screen)

    def show_browser(self):
        self._show_screen(self.browser_screen)

    def show_picker(self):
        """Picker is an overlay on Live video — switches stack to picker screen.
        VlcPlayer keeps running because we don't call release()."""
        self._show_screen(self.picker_screen)

    def show_menu(self):
        self._show_screen(self.menu_screen)

    def close_menu(self):
        """Return to whatever screen opened the menu (v0.7.0)."""
        target = getattr(self, "_menu_return", None)
        if target is None or target is self.menu_screen:
            target = self.live_screen if self.current_channel else self.boot_screen
        self._show_screen(target)

    def show_settings(self):
        self._settings_return = self.menu_screen
        self._show_screen(self.settings_screen)

    def close_settings(self):
        target = getattr(self, "_settings_return", None) or self.menu_screen
        self._show_screen(target)

    # ── Mode entry points ────────────────────────────────────────────────

    @staticmethod
    def _parse_catalog_arg() -> Optional[str]:
        """Parse `--catalog <path>` from sys.argv. Returns the path or None.
        Supported forms:
            --catalog C:\\Users\\me\\MyCatalog
            --catalog=C:\\Users\\me\\MyCatalog
        """
        argv = sys.argv[1:]
        i = 0
        while i < len(argv):
            arg = argv[i]
            if arg == "--catalog" and i + 1 < len(argv):
                return argv[i + 1]
            if arg.startswith("--catalog="):
                return arg.split("=", 1)[1]
            i += 1
        return None

    def _validate_catalog(self):
        """Pre-check how many catalog video files actually exist on disk.
        Logs a friendly one-time warning if zero files are found so the user
        knows to run `python scripts/test_pattern.py` first."""
        playable = 0
        missing = 0

        for ch in self.catalog.channels:
            for v in ch.videos:
                if os.path.exists(v.src):
                    playable += 1
                else:
                    missing += 1
            for c in ch.commercials:
                if os.path.exists(c.src):
                    playable += 1
                else:
                    missing += 1

        for m in self.catalog.library.movies:
            if os.path.exists(m.src):
                playable += 1
            else:
                missing += 1
        for s in self.catalog.library.shows:
            for e in s.episodes:
                if os.path.exists(e.src):
                    playable += 1
                else:
                    missing += 1

        self.catalog_playable_count = playable
        self.catalog_missing_count = missing

        if playable == 0:
            log.warning("=" * 60)
            log.warning("NO PLAYABLE VIDEO FILES DETECTED IN CATALOG")
            log.warning("=" * 60)
            log.warning(f"  Found {missing} catalog entries but 0 files exist on disk.")
            log.warning("  To fix this, run ONE of:")
            log.warning("")
            log.warning("    Option A — Generate SMPTE test patterns (needs ffmpeg):")
            log.warning("      python scripts/test_pattern.py")
            log.warning("")
            log.warning("    Option B — Drop your own MP4s at the catalog paths:")
            log.warning("      assets/mock/videos/<channel>/ep1.mp4")
            log.warning("      assets/mock/commercials/<channel>/ad1.mp4")
            log.warning("      assets/mock/library/movies/<file>.mp4")
            log.warning("")
            log.warning("  TV mode and Browser mode will not work until files exist.")
            log.warning("=" * 60)
        else:
            log.info(f"Catalog health: {playable} playable files, {missing} missing")

    def enter_tv_mode(self):
        """Called from boot screen's TV MODE button. Tunes to channel 1
        (or current channel if already in TV mode, using schedule state to
        join mid-stream)."""
        self.mode = "tv"
        if not self.catalog.channels:
            log.warning("No channels in catalog — staying on boot")
            self.show_boot()
            return

        # Sanity check — does the target channel actually have any
        # playable files? If not, abort TV mode with a clear message
        # rather than looping through VLC errors forever.
        target_ch = self.current_channel or self.catalog.channels[0]
        playable_in_ch = sum(1 for v in target_ch.videos if os.path.exists(v.src))
        if playable_in_ch == 0:
            log.error("=" * 60)
            log.error(f"NO PLAYABLE FILES in channel {target_ch.name} ({target_ch.id})")
            log.error("=" * 60)
            log.error(f"  Tried to play:")
            for v in target_ch.videos:
                marker = "OK" if os.path.exists(v.src) else "MISSING"
                log.error(f"    [{marker}] {v.src}")
            log.error("")
            log.error("  Run:  python scripts/test_pattern.py")
            log.error("  (requires ffmpeg in PATH)")
            log.error("  OR drop your own MP4s at the paths above.")
            log.error("=" * 60)
            self.show_boot()
            return

        # Reset failure tracker when entering TV mode cleanly
        self._consecutive_failures = 0

        # Always (re)tune — this uses schedule state to compute the proper
        # join position so we don't always restart from video 0
        self.tune_to_channel(target_ch.number)
        self.show_live()

    def enter_browser_mode(self):
        """Called from boot screen's BROWSER button or V key."""
        self.mode = "browser"
        self.show_browser()

    # ── TV mode: channel tuning + playback ───────────────────────────────

    def tune_to_channel(self, channel_number: int):
        """Tune to a channel — join whatever the broadcast timeline airs now.

        v0.7.0: the join position (and whether you land in a programme or in
        the middle of a commercial pod) comes from `timeline.py`, the same data
        the guide draws.  No queue, no mid-roll timer, no "10 minutes after you
        tuned in".
        """
        ch = find_channel_by_number(self.catalog, channel_number)
        if not ch:
            log.warning("No channel number %s", channel_number)
            return

        # Make sure this channel's lengths are real before building the timeline
        # (fast, container headers only).
        try:
            probe_channel(self._schedule_state, ch, allow_vlc=False)
        except Exception as e:
            log.debug("sync probe failed: %s", e)

        self.current_channel = ch
        tl = self.timeline_for(ch, rebuild=True)
        now = self.clock.now()
        air = tl.airing_at(now)
        if air is None:
            log.warning("Channel %s has no airings (no videos)", ch.name)
            return

        offset = air.position_at(now)
        self._set_airing(air)
        log.info(
            "Tuned to %s (ch %02d) — %s '%s' at %dm%02ds (cycle %.0f min)",
            ch.name, ch.number, "AD" if air.is_ad else "programme",
            air.video.title[:40], int(offset) // 60, int(offset) % 60,
            tl.cycle_length / 60.0,
        )

        # ── v0.5: channel-switch transition ────────────────────────────────
        # Cover the switch with full-frame snow (VideoOverlay) and release it
        # only once a real picture of the new media is on screen.
        self.show_live()
        self._pending_tune = {
            'channel': ch,
            'airing': air,
            'offset': offset,
        }
        self._raise_cover(black=False)
        self._tune_start_timer.start()
        # The channel number OSD, like a CRT/cable box: green digits in the
        # corner, drawn above the snow, held ~4 s then faded out.
        if hasattr(self.live_screen, "show_channel_osd"):
            self.live_screen.show_channel_osd(ch.number)
        log.info("Tuning to %s — snow up, joining at %ds", ch.name, int(offset))

    def _start_pending_tune(self):
        """Snow has been up long enough — start the new media underneath it.
        The snow stays up until _try_pending_seek() has seen a real picture."""
        tune = self._pending_tune
        self._pending_tune = None
        if not tune:
            return

        self.current_channel = tune['channel']
        self._play_airing(tune['airing'], tune['offset'])

    # ── Timeline plumbing (v0.7.0) ────────────────────────────────────────

    def _duration_lookup(self, ch: Channel):
        """VideoItem -> seconds, from the schedule cache or the catalog."""
        def lookup(v) -> float:
            d = self._schedule_state.known_duration(ch.id, v.id)
            if d > 0:
                return d
            return float(getattr(v, "duration", 0.0) or 0.0)
        return lookup

    def policy_for(self, ch: Channel) -> AdPolicy:
        base = AdPolicy(
            every_s=AD_BREAK_EVERY_S,
            min_ads=AD_BREAK_MIN_ADS,
            max_ads=AD_BREAK_MAX_ADS,
            min_video_s=AD_BREAK_MIN_VIDEO_S,
            tail_guard_s=AD_BREAK_TAIL_GUARD_S,
        )
        if not self.settings.get("ads_enabled", True):
            base = AdPolicy(every_s=0, min_ads=0, max_ads=0,
                            min_video_s=base.min_video_s,
                            tail_guard_s=base.tail_guard_s)
        return policy_for_channel(ch, base, jitter_s=AD_BREAK_JITTER_S)

    def timeline_for(self, ch: Channel, rebuild: bool = False) -> ChannelTimeline:
        """The channel's timeline (built once, rebuilt on demand)."""
        tl = self._timelines.get(ch.id)
        if tl is None:
            origin = self._schedule_state.get_or_init(ch.id).start_time
            tl = ChannelTimeline(ch, self._duration_lookup(ch), self.policy_for(ch),
                                 origin, dayparts=self._dayparts_for(ch))
            self._timelines[ch.id] = tl
        elif rebuild:
            tl.rebuild_if_changed()
        return tl

    @staticmethod
    def _dayparts_for(ch: Channel) -> dict:
        """Daypart windows declared by the channel's folders (v0.7.1).

        `Morning/`, `Late Night/`, `Afternoon/` … anywhere under the channel (for
        programmes) or under Commercials/ (for ads) activate that window.
        """
        names = set()
        for v in list(ch.videos) + list(ch.commercials):
            name = getattr(v, "daypart", "") or ""
            if name:
                names.add(name)
        out = {}
        for name in names:
            hours = DAYPART_FOLDERS.get(name.replace("_", " "))
            if hours:
                out[name] = hours
        return out

    def invalidate_timelines(self) -> None:
        """Forget every built timeline (durations changed, policy changed)."""
        self._timelines.clear()

    def _set_airing(self, air: Airing) -> None:
        """Make `air` the current item (queue kept for the UI code)."""
        self._airing = air
        self.current_queue = [PlayItem(kind=air.kind, video=air.video)]
        self.current_idx = 0

    def _play_airing(self, air: Airing, offset_s: float = 0.0) -> None:
        self._set_airing(air)
        self._play_current(seek_offset_seconds=max(0.0, offset_s))

    def _advance_live(self, cover: bool = False, next_segment: bool = False) -> None:
        """Jump to whatever the timeline is airing right now.

        `next_segment` is for the case where the current airing has just run out
        (the file ended, or the tick says its slot is over): it starts from the
        airing after it and walks forward until an airing is still running.  That
        walk is what stops the player falling behind its own cover: a segment
        whose slot is already over must not be replayed at `position_at(now)`,
        because that seeks past the end of the file and never lands.
        """
        if not self.current_channel:
            return
        tl = self.timeline_for(self.current_channel)
        now = self.clock.now()
        if next_segment and self._airing is not None:
            # Start one segment later: the current one is over (or its file
            # ended), and replaying it is exactly the “same ad restarts” loop.
            start = tl.next_after(self._airing)
            air = tl.airing_at_or_after(now, start)
        else:
            air = tl.airing_at(now)
        if air is None:
            return
        if air.end <= now:
            # Safety: never start an airing whose slot is already over.
            air = tl.airing_at(now) or air
        if cover:
            self._raise_cover(black=True)
        self._play_airing(air, air.position_at(now))

    def _live_tick(self) -> None:
        """Once a second: make sure the picture is still the live airing.

        The timeline is the boss.  This is what makes a programme that overruns
        its slot end on time, a channel change land in the right place, and a
        pause not silently become a 40-minute DVR delay.

        v0.7.7: `_cover_pending` no longer blocks the tick.  A seek waiting to
        settle used to suppress it for a second or two per item, so the tick ran
        late, every join was further into its slot, and short commercials ended
        up joined at their last second (the “ad blinks then jumps” report).  A
        visual cover (`_snow_active`) still holds it back, because that is a
        channel change in progress.
        """
        if (self.mode != "tv" or self.current_channel is None
                or self._airing is None or self._snow_active
                or self._pending_tune):
            return
        if self.player is None:
            return
        now = self.clock.now()
        if now < self._airing.end - 0.25:
            return
        # A media that has not started yet gets a grace period, so a slow disk
        # cannot make us skip an item before it ever appears.
        if not self._media_started and now < self._airing.end + 5.0:
            return
        log.info("Timeline: %s ended — following live",
                 "ad" if self._airing.is_ad else "programme")
        self._advance_live(next_segment=True)

    def next_break_in(self) -> float:
        """Seconds until the next ad pod starts (used by the info card)."""
        if not (self.current_channel and self._airing):
            return 0.0
        tl = self.timeline_for(self.current_channel)
        if self._airing.is_ad:
            return 0.0
        now = self.clock.now()
        for air in tl.airings(now, now + 3 * 3600, limit=200):
            if air.is_ad and air.start > now:
                return max(0.0, air.start - now)
        return 0.0

    def _raise_cover(self, black: bool = False):
        """Cover the picture and (re)start its safety net.

        Used for both a channel change (snow) and a resume after a break
        (black).  The timer is restarted rather than armed again, so a cover
        raised while an older one is still pending can never be released early
        by the older shot.
        """
        self._snow_active = True
        self._cover_pending = True
        if hasattr(self, "live_screen"):
            self.live_screen.begin_tune(black=black)
        self._snow_guard.start(int(COVER_MAX_S * 1000) + 1500)

    def _release_snow(self):
        """Drop the cover (fades out over ~250 ms) and restore the volume."""
        if self._snow_guard.isActive():
            self._snow_guard.stop()
        self._cover_pending = False
        if self._tune_muted:
            self._tune_muted = False
            if self.player:
                try:
                    self.player.set_volume(self.volume)
                except Exception:
                    pass
        if not self._snow_active:
            return
        self._snow_active = False
        if hasattr(self, "live_screen"):
            self.live_screen.end_tune()
            # v0.7.7: the picture is really there — pop the channel banner for a
            # few seconds, the “just flicked onto this station” moment.
            if (self.mode == "tv" and self.current_channel
                    and hasattr(self.live_screen, "show_banner")):
                self.live_screen.show_banner()

    def _finish_cover(self):
        """The picture is (or will never be) right — stop driving the seek and
        let the cover fade out."""
        self._cover_pending = False
        self._seek_target_s = 0.0
        self._pending_seek_seconds = 0.0
        self._cover_wait = None
        self._seek_poll_timer.stop()
        self._release_snow()

    def _play_current(self, seek_offset_seconds: float = 0.0):
        """Play the item at self.current_idx. Optionally seek to a specific
        offset within the video once VLC loads it."""
        if not self.current_queue or not self.current_channel:
            return

        if self.current_idx >= len(self.current_queue):
            self.current_idx = 0

        item = self.current_queue[self.current_idx]
        ch = self.current_channel

        # ── File-existence guard ──────────────────────────────────────────
        if not os.path.exists(item.video.src):
            if item.video.src not in self._missing_files_warned:
                self._missing_files_warned.add(item.video.src)
                log.warning(f"File not found, skipping: {item.video.src}")
            return self._advance_after_failure()

        # File exists — reset failure counter and actually play
        self._consecutive_failures = 0
        self._ensure_player()

        # v0.7.0: from here until VLC reports MediaPlayerPlaying, anything the
        # player says about position belongs to the *previous* media.  The
        # cover waits for this flag (see _try_pending_seek).
        self._media_started = False
        self._media_requested_at = time.time()
        try:
            file_size = os.path.getsize(item.video.src)
        except OSError:
            file_size = 0

        # While the cover is up, keep the audio down: on a slow-seek file you
        # would otherwise hear the first seconds of the episode and then jump
        # (the same artefact as the visible frame-0 flash).
        if self._snow_active and self.player:
            self._tune_muted = True
            try:
                self.player.set_volume(0)
            except Exception:
                pass

        # ── Playback ───────────────────────────────────────────────────────
        # No :start-time media option any more.  For MPEG-PS captures whose
        # timestamps are broken, libvlc jumps to the wrong place with it
        # (measured on the real catalog: asked for 900 s, landed at 20 s).
        # The join position is reached by seeking by fraction after play().
        self.player.play_item(
            src=item.video.src,
            deinterlace=ch.deinterlace,
            aspect=self._aspect_for(item.video.src),
            crop=self._crop_for(item.video.src),
        )

        # ── Where we want to be in this video ──────────────────────────────
        # Only a duration we actually trust may be used to turn a target time
        # into a position fraction: libvlc's get_length() claims 37 h for a
        # 44-minute capture, and dividing by that is exactly what made the
        # channel start at the beginning of the file instead of mid-way.
        trusted = 0.0
        if seek_offset_seconds > 0:
            try:
                trusted = self._schedule_state.known_duration(ch.id, item.video.id)
            except Exception:
                trusted = 0.0

        self._seek_target_s = seek_offset_seconds if seek_offset_seconds > 1.0 else 0.0
        # v0.7.2: a seek needs a real length to aim at.
        #   * no known length (an ad that was never probed) -> play from the
        #     start instead of guessing with a 30-minute assumption, which used
        #     to land 11 s into a 13 s ad at 0.6 % of the file and never settle;
        #   * a target at/after the end (the slot is already over) -> clamp to
        #     the last second instead of seeking past EOF.
        if self._seek_target_s > 0:
            if trusted <= 0.5:
                if item.kind == "ad" and self._seek_target_s > 5.0:
                    # A commercial whose slot is already well past its start and
                    # which has no length to seek into: replaying it from 0:00 is
                    # the “same ad restarts” glitch, so move to the next segment.
                    # (Never for a programme — starting a 44-minute show at 0:00
                    # is better than skipping it entirely.)
                    log.info("No length for '%s' and %.0fs into its slot — "
                             "skipping to the next airing",
                             item.video.title[:40], self._seek_target_s)
                    self._seek_target_s = 0.0
                    self._cover_pending = False
                    QTimer.singleShot(0, lambda: self._advance_live(next_segment=True))
                    return
                log.info("No trusted length for '%s' — starting at 0:00",
                         item.video.title[:40])
                self._seek_target_s = 0.0
            elif self._seek_target_s >= trusted - min(2.0, max(0.4, trusted * 0.5)):
                # Less than a couple of seconds left in this slot (half of it, for
                # a very short ad): playing it is a one-frame blink.  The
                # timeline has already moved on, so join the next airing instead
                # (v0.7.7 — this is what the “ad shows for a second and jumps”
                # pattern was).
                log.info("Join %.1fs is at the end of '%s' (%.0fs) — skipping to "
                         "the next airing",
                         self._seek_target_s, item.video.title[:40], trusted)
                self._seek_target_s = 0.0
                self._cover_pending = False
                QTimer.singleShot(0, lambda: self._advance_live(next_segment=True))
                return
        self._seek_trusted_len = trusted
        self._seek_tries = 0
        self._seek_seeks = 0
        self._seek_last_issue = 0.0
        self._pending_seek_seconds = self._seek_target_s
        # The cover's referee: it only lets the picture through once the clock
        # is at the target *and* still moving, and never before a short settle
        # window that scales with the file (a 1.2 GB MPEG-PS needs about a
        # second after the seek before its first new frame is on the vout).
        settle_s = 0.20 + min(1.0, file_size / 1.2e9) * 0.9
        self._cover_wait = CoverWait(
            self._seek_target_s,
            first_frame_s=COVER_FIRST_FRAME_S,
            confirm_s=COVER_CONFIRM_S,
            stall_s=COVER_STALL_S,
            deadline_s=COVER_MAX_S,
            min_hold_s=settle_s,
        )

        # Under a cover we always poll: with a target to seek to, or (joined at
        # the very start) simply waiting until the new media has really played.
        # The cover is lifted by the first frame that actually exists, not by a
        # stopwatch — see _try_pending_seek().
        if self._seek_target_s > 0 or self._snow_active:
            self._cover_pending = True
            if not self._seek_poll_timer.isActive():
                self._seek_poll_timer.start()
        else:
            self._cover_pending = False
            self._seek_poll_timer.stop()

        self.live_screen.update_now_playing(item, ch, self.current_idx)

    def _learn_current_duration(self):
        """Record the playing item's real length — but only if the value is
        plausible for the file on disk.  libvlc reports 37 hours for a
        44-minute MPEG-PS capture, and that number used to be written straight
        into schedule_state.json (where it wrecked the schedule).

        v0.7.6: commercials are learned too.  An ad with no known length cannot
        be seeked into (the timeline assumes 30 s), so it restarted from 0 on
        every join and the pod drifted — the “little repeating glitch”.
        """
        if not (self.current_channel and self.player and self.current_queue
                and 0 <= self.current_idx < len(self.current_queue)):
            return
        item = self.current_queue[self.current_idx]
        if item.kind not in ("main", "ad"):
            return
        if self.player.current_src() != item.video.src:
            return
        length_ms = self.player.current_length_ms()
        if length_ms <= 0:
            return
        seconds = length_ms / 1000.0
        try:
            size = os.path.getsize(item.video.src)
        except OSError:
            size = 0
        if not plausible(seconds, size):
            if not getattr(self, "_implausible_length_warned", False):
                self._implausible_length_warned = True
                log.info("Ignoring libvlc length %.0fs for '%s' (implausible for "
                         "%.0f MB) — keeping the probed length",
                         seconds, item.video.title, size / 1e6)
            return
        if self._schedule_state.set_duration(
                self.current_channel.id, item.video.id, seconds, source="play"):
            # The cycle just changed length: rebuild before the next airing so
            # the timeline and the picture cannot disagree.
            self.invalidate_timelines()

    def _try_pending_seek(self):
        """Drive playback to `_seek_target_s`, then lift the cover.

        libvlc's get_length() cannot be trusted for every container, so this
        works closed-loop on the two things that CAN be trusted here:

            get_time()      — real seconds inside the media
            get_position()  — a fraction of the REAL duration

        Each attempt corrects the fraction proportionally from where the
        player actually is, so it converges in one or two tries even when all
        we have is a rough duration.  Measured on the real catalog: asking the
        44-minute MPEG-PS for 1500 s via set_time() lands at 20 s, while
        set_position(0.558) lands at 1500 s.

        v0.6.5 — why the cover is not lifted on a stopwatch any more:
        get_time() reaching the target only means the *demuxer* is there.  The
        vout can still be holding the previous picture for a moment (it is the
        stale-frame class of bug: Kawaii TV showed one frame of the old clip
        for about a second after the snow went away, then the episode started).
        So the cover comes off when (a) the position is at the target — or, for
        a join at 0:00, when the new media has actually played a moment — AND
        (b) the clock moved between two polls, which is the only proof we get
        that the decoder is rolling new frames.
        """
        if not self._cover_pending or not self.player:
            self._seek_poll_timer.stop()
            return

        now = time.time()
        self._seek_tries += 1
        t = self.player.get_time_ms() / 1000.0
        loaded = self.player.current_length_ms() > 0 or t > 0.0

        # v0.7.0: nothing counts until libvlc has actually *started the new
        # media*.  Right after set_media() the player can still report the old
        # clip's time, which used to look like "at target" and lifted the cover
        # on a stale frame (the Kawaii TV flash when changing back to it).
        if not self._media_started:
            # If MediaPlayerPlaying never reaches us (event-thread hiccup), a
            # clock that has reset to the first second is proof enough that a
            # new media is running.
            if loaded and t <= 1.0 and now - self._media_requested_at > 0.2:
                self._media_started = True
            else:
                if now - self._media_requested_at > COVER_MAX_S:
                    self._finish_cover()
                return

        if self._cover_wait is None:
            self._finish_cover()
            return
        decision = self._cover_wait.update(now, t, loaded)
        if decision == RELEASE:
            log.info("Cover released: wanted %.0fs, VLC at %.1fs (%d seek(s))",
                     self._cover_wait.target_s, t, self._seek_seeks)
            self._finish_cover()
            return
        if decision == GIVE_UP:
            if self._cover_wait.landed:
                log.warning("VLC clock frozen at %.1fs (wanted %.0fs) — "
                            "showing the picture anyway", t, self._cover_wait.target_s)
            else:
                log.warning("Seek to %.0fs did not settle in %.1fs (player at "
                            "%.1fs) — showing the picture anyway",
                            self._cover_wait.target_s,
                            self._cover_wait.elapsed(now), t)
            self._finish_cover()
            return

        if self._cover_wait.landed:
            # Already at the target: do not issue another seek, just wait for
            # the clock to prove the decoder is rolling (one or two polls).
            return

        target = self._seek_target_s
        if not loaded or target <= 0:
            return                     # nothing to seek yet; keep waiting

        # Space the seeks out: on a 1.2 GB MPEG-PS every seek makes the
        # demuxer rescan, so re-issuing one every 100 ms made tuning slower
        # instead of faster. One good seek + a patient check is much quicker.
        if self._seek_seeks and now - self._seek_last_issue < 1.2:
            return
        if self._seek_seeks >= 6:
            return                     # last seek is still settling
        self._seek_last_issue = now
        self._seek_seeks += 1

        frac = self.player.current_position()
        if t > 5.0 and frac > 0.001:
            frac = frac * (self._seek_target_s / t)      # proportional correction
        elif self._seek_trusted_len > self._seek_target_s:
            frac = self._seek_target_s / self._seek_trusted_len
        else:
            frac = min(0.99, self._seek_target_s / 1800.0)
        frac = max(0.0, min(0.995, frac))
        self.player.seek_to(frac)

    def _save_schedule_state(self):
        """Persist schedule state to disk (called every 2 s and on close).
        Position is wall-clock based, so only the durations cache can change."""
        self._learn_current_duration()
        self._schedule_state.save(self._state_file)

    def _advance_after_failure(self):
        """Skip to the next airing after a missing-file or VLC error.

        Rate-limited: six failures in a row and we give up and go to boot.
        One broken ad must never take the channel down — the timeline simply
        moves on to the next segment.
        """
        now = time.time()
        if now - self._last_failure_time < 5:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 1
        self._last_failure_time = now

        if self._consecutive_failures >= 6:
            log.error("=" * 60)
            log.error("ALL ITEMS IN QUEUE FAILED — aborting playback.")
            log.error("=" * 60)
            log.error(f"  Channel: {self.current_channel.name if self.current_channel else '(none)'}")
            log.error(f"  Tried {self._consecutive_failures} items in a row; none playable.")
            log.error("")
            log.error("  Run:  python scripts/test_pattern.py")
            log.error("  (requires ffmpeg in PATH)")
            log.error("  OR drop your own MP4s at the catalog paths.")
            log.error("=" * 60)
            self.show_boot()
            return

        self.current_idx = (self.current_idx + 1) % len(self.current_queue)
        # Use QTimer.singleShot so we don't recurse on the call stack
        # (which could overflow if the whole queue is missing) AND to add
        # a small (10ms) delay so we don't hammer the disk with stat() calls.
        QTimer.singleShot(10, self._skip_to_next_airing)

    def _skip_to_next_airing(self):
        """Play the segment that follows the one that just failed."""
        if self._airing is None or self.current_channel is None:
            QTimer.singleShot(10, self._advance_live)
            return
        tl = self.timeline_for(self.current_channel)
        nxt = tl.next_after(self._airing)
        if nxt is None:
            QTimer.singleShot(10, self._advance_live)
            return
        self._play_airing(nxt, 0.0)

    def _ensure_player(self):
        """Create VlcPlayer on first playback. We do this lazily because VLC
        needs a valid winId() to bind set_hwnd() to, and that's only available
        after the video widget is shown."""
        if self.player is None:
            self.player = VlcPlayer(self.video_widget, parent=self, crop=VIDEO_CROP,
                                    level_audio=self.settings.get("audio_leveling", True))
            self.player.ended.connect(self._on_media_ended)
            self.player.error.connect(self._on_media_error)
            self.player.position.connect(self._on_position)
            # MediaPlayerPlaying — the new media is really running. Used to keep
            # the tuning cover up until the *new* clip is playing (v0.7.0).
            self.player.started.connect(self._on_media_started)
            self.player.set_volume(self.volume)

    def _on_media_started(self):
        self._media_started = True
        self._media_started_at = time.time()

    def _on_media_ended(self):
        """The file ended — advance to the *next* segment of the timeline.

        Not `airing_at(now)`: a file that ends a fraction of a second before its
        scheduled end would otherwise resolve to the same airing again and
        replay its tail in a loop.
        """
        if self.mode != "tv" or self._airing is None or self.current_channel is None:
            return
        tl = self.timeline_for(self.current_channel)
        now = self.clock.now()
        # The file ended: always move at least one segment on, then keep walking
        # while those segments are already over.
        nxt = tl.airing_at_or_after(now, tl.next_after(self._airing))
        if nxt is None:
            return
        log.info("Media ended — next airing (%s)", "ad" if nxt.is_ad else "programme")
        self._play_airing(nxt, nxt.position_at(now))

    def _on_media_error(self, msg: str):
        """VLC reported a playback error. Rate-limit so we don't spam; abort
        if too many consecutive errors in 5 seconds."""
        log.error(f"VLC error: {msg}")
        # Use the same rate-limiting as missing files
        self._advance_after_failure()

    def _on_position(self, pos: float):
        if self.player:
            self.live_screen.update_position(pos, self.player.current_length_ms())

    # ── Per-file display aspect (v0.7.1) ─────────────────────────────────

    def _aspect_for(self, src: str) -> str:
        """The display aspect for one file: its override, else the default."""
        preset = self.display.get(src, "aspect")
        if not preset or preset == "auto":
            return VIDEO_ASPECT
        return preset

    def _crop_for(self, src: str) -> str:
        """The crop geometry for one file: its override, else 16:10."""
        return self.display.get(src, "crop") or VIDEO_CROP

    def cycle_aspect(self) -> None:
        """Hotkey A: cycle the aspect override for the file on screen and keep it."""
        if not (self.player and self.current_queue):
            return
        item = self.current_queue[self.current_idx]
        preset = self.display.next_preset(item.video.src, "aspect")
        self.player.set_aspect(self._aspect_for(item.video.src))
        label = PRESET_LABELS.get(preset, preset)
        log.info("Aspect for '%s' -> %s", item.video.title[:40], preset)
        if hasattr(self.live_screen, "show_system_osd"):
            self.live_screen.show_system_osd(f"ASPECT  {label}")

    def cycle_crop(self) -> None:
        """Hotkey C: cycle the crop override for the file on screen and keep it.

        The crop is an instance option (16:10) on this build; the runtime
        `video_set_crop_geometry()` call is the only per-file route.  If a VLC
        build ignores it, the toast still shows the choice — and the file stays
        correct on builds that honour it.
        """
        if not (self.player and self.current_queue):
            return
        item = self.current_queue[self.current_idx]
        preset = self.display.next_preset(item.video.src, "crop")
        self.player.set_crop(self._crop_for(item.video.src))
        label = CROP_LABELS.get(preset, preset)
        log.info("Crop for '%s' -> %s", item.video.title[:40], preset)
        if hasattr(self.live_screen, "show_system_osd"):
            self.live_screen.show_system_osd(f"CROP  {label}")

    # ── Volume (v0.7.0) ───────────────────────────────────────────────────

    def set_volume(self, level: int, show_osd: bool = True) -> None:
        level = max(0, min(100, int(level)))
        self.volume = level
        self.settings.set("volume", level)
        if self.player and not self._tune_muted:
            try:
                self.player.set_volume(level)
            except Exception:
                pass
        if show_osd and hasattr(self.live_screen, "show_volume_osd"):
            self.live_screen.show_volume_osd(level)

    def change_volume(self, delta: int) -> None:
        self.set_volume(self.volume + int(delta))

    # ── Pause / clock / probe hooks (v0.7.0) ─────────────────────────────

    def on_resume_from_pause(self) -> None:
        """Pause freezes the picture; it does not stop the broadcast.

        A long pause would otherwise leave the app showing a delayed feed that
        disagrees with the guide (and with the ads).  Coming back more than 20 s
        behind live rejoins the timeline, like changing channel back to it.
        """
        if self.mode != "tv" or self._airing is None or not self.player:
            return
        now = self.clock.now()
        live_pos = self._airing.position_at(now)
        current = self.player.get_time_ms() / 1000.0
        behind = live_pos - current
        if behind > 20.0:
            log.info("Rejoining live: paused %.0fs behind the timeline", behind)
            self._advance_live(cover=True)

    def _on_clock_changed(self, offset_s: float) -> None:
        self.settings.set("clock_offset_s", float(offset_s))
        # The schedule is epoch-based, so a clock change moves every channel —
        # exactly like setting the clock on a VCR.
        log.info("Clock offset set to %+.0f s", offset_s)

    def _on_probe_finished(self) -> None:
        try:
            self._schedule_state.save(self._state_file)
        except Exception as e:
            log.warning("Could not save schedule state: %s", e)
        # Real lengths are in: rebuild every timeline so the guide and the
        # player agree on where the breaks are.
        self.invalidate_timelines()

    # ── TV mode: channel navigation ───────────────────────────────────────

    def channel_up(self):
        if not self.current_channel:
            if self.catalog.channels:
                self.tune_to_channel(self.catalog.channels[0].number)
            return
        idx = next(
            (i for i, ch in enumerate(self.catalog.channels) if ch.id == self.current_channel.id),
            0,
        )
        next_idx = (idx + 1) % len(self.catalog.channels)
        self.tune_to_channel(self.catalog.channels[next_idx].number)

    def channel_down(self):
        if not self.current_channel:
            if self.catalog.channels:
                self.tune_to_channel(self.catalog.channels[-1].number)
            return
        idx = next(
            (i for i, ch in enumerate(self.catalog.channels) if ch.id == self.current_channel.id),
            0,
        )
        prev_idx = (idx - 1) % len(self.catalog.channels)
        self.tune_to_channel(self.catalog.channels[prev_idx].number)

    def toggle_play_pause(self):
        if self.player:
            self.player.pause()
    # ── Browser mode: library playback (no commercials) ────────────────────

    def play_library_item(self, item: VideoItem):
        """Play a Library item on-demand. No commercial injection, no per-
        channel deinterlace/aspect (use sensible defaults)."""
        # File-existence guard — don't try VLC on a missing file
        if not os.path.exists(item.src):
            log.error("=" * 60)
            log.error(f"LIBRARY FILE NOT FOUND: {item.src}")
            log.error("=" * 60)
            log.error("  Run:  python scripts/test_pattern.py")
            log.error("  (requires ffmpeg in PATH)")
            log.error("  OR drop your MP4 at the path above.")
            log.error("=" * 60)
            return

        log.info("Library playing: %s", item.title)
        # Learn the length up-front: the progress bar shows this instead of
        # waiting for libvlc (which may briefly report the previous file's
        # length right after the media switch).
        if not item.duration:
            try:
                item.duration = probe_duration_seconds(item.src, allow_vlc=False)
            except Exception:
                item.duration = 0.0
        # Build a 1-item "queue" — just this video, looping back when done.
        self._release_snow()
        self._airing = None     # library playback is not on the broadcast timeline
        self.current_channel = None
        self.current_queue = [PlayItem(kind="main", video=item)]
        self.current_idx = 0
        self._ensure_player()
        # Library items — assume progressive MP4s, no deinterlace, same crop as
        # the channels, with any per-file aspect/crop override applied.
        self.player.play_item(src=item.src, deinterlace="none",
                              aspect=self._aspect_for(item.src),
                              crop=self._crop_for(item.src))
        # Use the Live screen for playback UI (overlay still works)
        self.live_screen.update_now_playing(
            PlayItem(kind="main", video=item),
            Channel(
                id="library", number=0, name="LIBRARY", abbrev="LIB",
                videos=[], commercials=[],
            ),
            0,
        )
        self.show_live()

    # ── Input dispatch (router) ──────────────────────────────────────────

    def _dispatch_action(self, action: str):
        """Route a unified action (from keyboard or gamepad) to the current
        screen's handle_input()."""
        # Global quit works on any screen
        if action == "quit":
            self.close()
            return

        # Global volume (v0.7.0): works on every screen, with its own OSD.
        if action == "vol_up":
            self.change_volume(5)
            return
        if action == "vol_down":
            self.change_volume(-5)
            return

        # Global aspect/crop cycle (v0.7.1): fixes one stubborn commercial on the
        # fly and remembers the choice for that file.
        if action == "aspect":
            self.cycle_aspect()
            return
        if action == "crop":
            self.cycle_crop()
            return

        # Global menu (v0.7.0): M used to work only on the Live screen.
        if action == "menu" and self.stack.currentWidget() is not self.menu_screen:
            self._menu_return = self.stack.currentWidget()
            self.show_menu()
            return

        current = self.stack.currentWidget()
        if hasattr(current, "handle_input"):
            current.handle_input(action)

    # ── Moving the window (v0.6.5) ────────────────────────────────────────
    # The window is frameless at the CRT's 720x480, so there is no title bar to
    # grab.  It can be dragged from anywhere.  On the Live screen the picture is
    # a native VLC child window, so a mouse press over it never reaches Qt;
    # VideoOverlay (the transparent window that already sits above the video)
    # forwards it here instead, which is why dragging works over the video too.

    def begin_window_drag(self, global_pos: Optional[QPoint]):
        if global_pos is None:
            return
        self._drag_offset = global_pos - self.pos()

    def drag_window_to(self, global_pos: Optional[QPoint]):
        if self._drag_offset is None or global_pos is None:
            return
        self.move(global_pos - self._drag_offset)

    def end_window_drag(self):
        if self._drag_offset is None:
            return
        self._drag_offset = None
        self._save_window_position()

    def mousePressEvent(self, event):
        # Any left press on a part of the UI that does not use the mouse starts
        # a window drag (no screen has mouse controls).
        if event.button() == Qt.LeftButton:
            self.begin_window_drag(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.drag_window_to(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_offset is not None:
            self.end_window_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ── Remembering where the window was left (v0.6.5) ──

    @staticmethod
    def _screen_list() -> list:
        """The screens Qt knows about, as plain dicts for window_state.py.

        `QScreen.isPrimary()` does not exist in PySide6 6.12, so primary-ness is
        `scr is QGuiApplication.primaryScreen()`.
        """
        primary = QGuiApplication.primaryScreen()
        out = []
        for scr in QGuiApplication.screens():
            g = scr.availableGeometry()
            out.append({
                "name": scr.name(),
                "primary": scr is primary,
                "available": (g.x(), g.y(), g.width(), g.height()),
            })
        return out

    def _restore_window_position(self):
        try:
            saved = window_state.load(self._window_state_file)
            x, y = window_state.pick_position(
                saved, self._screen_list(), (self.width(), self.height()))
            self.move(x, y)
            log.info("Window placed at %d,%d (remembered screen: %s)",
                     x, y, saved.get("screen") or "first run")
        except Exception as e:
            log.warning("Could not restore the window position: %s", e)

    def _save_window_position(self):
        try:
            scr = self.screen() or QGuiApplication.primaryScreen()
            window_state.save(self._window_state_file,
                              scr.name() if scr else "", self.x(), self.y())
        except Exception as e:
            log.debug("Could not save the window position: %s", e)

    def _rescue_window_position(self):
        """A monitor was plugged in or removed — never leave the window lost.

        There is no title bar and no taskbar button to bring it back with, so a
        window left on a screen that no longer exists would be unreachable.
        """
        try:
            screens = self._screen_list()
            if not screens:
                return
            size = (self.width(), self.height())
            if window_state.is_on_any_screen((self.x(), self.y()), size, screens):
                return
            x, y = window_state.pick_position({"x": self.x(), "y": self.y()}, screens, size)
            log.warning("Window was off-screen after a monitor change — moved to %d,%d", x, y)
            self.move(x, y)
            self._save_window_position()
        except Exception as e:
            log.debug("Window rescue failed: %s", e)

    # ── Qt event hooks ────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        # Route Qt keyboard events to the InputController for translation.
        if self.input.handle_qt_key(event.key()):
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        # Remember where the window was (per screen), so the next launch opens
        # in the same place instead of wherever Windows feels like putting it.
        self._save_window_position()
        # Save schedule state on exit so next session resumes correctly
        try:
            self._save_schedule_state()
            log.info("Saved schedule state on close")
        except Exception as e:
            log.warning(f"Failed to save schedule state on close: {e}")
        if self.player:
            self.player.release()
        if hasattr(self, "overlay"):
            self.overlay.close_overlay()
        self.input.shutdown()
        super().closeEvent(event)


# ── Entry point ─────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # Load bundled fonts (VT323, Share Tech Mono, Oxanium, etc.) if present
    load_fonts()

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
