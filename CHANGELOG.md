# nullaOS changelog

## v0.7.7 — the channel banner, and the ad-blink fix

The two things in this build are independent: a new bottom info bar for Live TV
(the user’s “better place for the I card”), and the fix for the one-second ad
blinks reported in the 00:42 log.

### 1. Channel banner (replaces the full-screen “I” card)

Flick onto a station and a bar rises at the bottom for a few seconds — the thing
a cable box does. It shows:

* the channel number and network logo (left, with the logo fading in when the
  channel has one),
* the programme title (28 px, white),
* its start–end times (20 px, gold, using the same clock/12-24 h setting as the
  guide),
* `NEXT` and the following programme's title (20 px, muted blue),
* a one-line description from the `<file>.txt` next to the video (20 px, grey).

Details that matter:
* **`I` toggles it** (10 s when opened by hand, 6 s when automatic); BACK closes
  it before leaving to boot, in TV and library mode alike;
* it **auto-appears after a tune**, hung off `_release_snow()` — i.e. once the
  picture is actually up, never over the snow;
* the content is resolved **once per appearance**, not per paint (25 fps); during
a commercial pod it still names the *programme* because it reads
  `programme_blocks()`, not the playing item;
* the watermark fades out by `1 - banner_alpha` while the bar is up, so the two
  never overlap at the bottom-left;
* geometry comes from the measured safe box: x 32…680, bottom 442, height 104.

### 2. The ad blinks (tick suppressed by a settling seek)

See the previous entry — `_live_tick` no longer waits for `_cover_pending`,
`next_after()` has a 50 ms epsilon, and a join with less than 2 s left skips to
the next airing instead of showing one frame.
**Tests:** 42 timeline tests (incl. `TickLoopTests`: join offset never exceeds
3 s over 40 simulated minutes), 8 display, 12 cover, 19 window, 15 playlist,
11 probe, and **41/41** offscreen `MainWindow` checks — now including the banner:
content (number/title/times), paint-over-picture, and `I` toggling.
`scratch/sim_transitions.py` drives the real window with a fake 1.2 s-load player
for 90 simulated minutes: 61 airings, offset constant, zero problems.
First banner paint: **6.3 ms** (the 6 s stall in the WIP handover was a harness
artefact — no font warm-up needed).

### 3. Smaller: a repository checkout starts on the mock catalog again

The project-local `catalog/` was auto-detected whenever the folder held *any*
entry. The repository ships `catalog/README.md` (and nothing else), so a fresh
clone counted that as a real catalog, found zero channels and sat there. The
autodetect now requires at least one channel **folder**, so a clone falls back to
the mock catalog and prints the "generate test patterns" guidance instead.

## v0.7.6 — commercials know their length (and stop restarting)

From the 00:34 log: `No trusted length for 'ベイクック…' — starting at 0:00`, then
`Timeline: ad ended`, then the same ad again a second later.

**Cause.** Ad durations were never locked, so the timeline assumed 30 s per ad
while the files are 12–15 s.  A join 17 s into a “30 s” slot could not be seeked
(v0.7.2 rightly refuses to seek without a length), so the ad restarted at 0:00,
finished early, the tick moved to the next slot, and the pod visibly repeated
itself.  Programmes were unaffected because their lengths are probed.

**Fix.**
* `probe_channel()` uses the full probe chain for commercials again (container →
  ffprobe → filename hint → libvlc), not just the fast header read.  One slow
  pass at startup, then the values are locked in `schedule_state.json`;
* `_learn_current_duration()` now records **ad** lengths learned during playback
  too, and invalidates the timelines so the next pod is exact;
* when an ad still has no known length and its slot is already more than 5 s old,
  the app skips to the next airing instead of replaying the ad from the start.
  This never applies to programmes (a 44-minute show starting at 0:00 is better
  than skipping it).

Existing `schedule_state.json` files pick this up automatically on the next
launch: the startup probe fills the missing ad lengths.

**Tests:** 35/35 offscreen checks, timeline 38, display 8, cover 12, window 19,
playlist 15, probe 11. **Not verified on the Aiwa.**

## v0.7.5 — guide: LEFT no longer loses the highlight

Pressing LEFT in the guide moved the cursor to the previous programme, but the
window was clamped to “now − 30 min”. When that previous programme sat entirely
before the window it was never drawn, so there was no gold cell at all — the
highlight looked like it had been switched off.

* the guide may now page **back up to 6 hours** (it was half an hour), so the
  previous programmes are actually shown;
* if the cursor still cannot be followed (the 72 h forward horizon, or the 6 h
  back limit), it is clamped inside the window instead of leaving the grid —
  the highlight is always on screen;
* regression check in the offscreen run (`left keeps the highlight on screen`).

**Tests:** 35/35 offscreen checks, and the usual suites (timeline 38, display 8,
cover 12, window 19, playlist 15, probe 11). **Not verified on the Aiwa.**

## v0.7.4 — the guide behaves like an EPG again

Baseline: v0.7.3.

### Guide

* **No more timestamp inside a cell.** The small `02:52` under a title (visible in
  Screenshot_11) was the programme's start time; it is gone. The time ruler at the
  top and the NOW line are the time reference.
* **Titles wrap to two lines**, elided with `…` only when there is still text left
  (the Comcast reference does the same: “Zachary
  Beaver Came…”). One-line elision is used when the whole title fits on line one.
* **Stretched cells.** Every programme gets at least 96 px and the row always
  fills the grid, so a 10-minute item is no longer a 40 px sliver — the old
  “slot” look is back, while the widths still follow the real durations.
* **Channel column: logo only.** The number was redundant (the OSD shows it when
  flicking); channels without a logo keep number + abbreviation so the row is
  never empty.
* **No gold ring** around the channel cell — the programme cell carries the
  selection again.
* **The cursor moves like a real guide.** LEFT/RIGHT move the highlight from one
  programme to the next; the window pages when the cursor reaches the edge, and
  the info plate at the top instantly shows the focused programme's full title,
  time and channel (whether it is on now or hours ahead). The gold cell is the
  focused one, not “whatever is at the left edge”.

### Also in this build (v0.7.3, first shipped here)

* **C** cycles the crop live and remembers it per file, independent of **A**
  (aspect) — `display_overrides.json` now stores `{aspect, crop}` per file.
* Boot footer: version 24 px at y=438, 5 px below the TV/BROWSER chips.
* Watermark 8 px lower (450) at 60 % opacity.

**Tests:** `test_display.py` 8, `test_timeline.py` 38, cover 12, window 19,
playlist 15, probe 11; offscreen `MainWindow` run **34/34** (guide focus moves,
window pages, 72 h horizon). **Not verified on the Aiwa.**

## v0.7.3 — crop hotkey, guide selection ring, footer spacing, softer watermark

Baseline: v0.7.2.

### 1. C crops — live, and remembered

A cycles the display aspect; **C now cycles the crop** (`video_set_crop_geometry`,
retried at 0/350/1200 ms because the vout starts late). Both are stored
independently per file in `display_overrides.json`:

```json
{"C:/Media/Kawaii/Commercials/x.mp4": {"aspect": "2.21:1", "crop": "16:9"}}
```

Old files that stored a bare string are read as aspect-only. Every item re-applies
its own crop when it starts, so the setting follows the file, not the channel.
**Caveat:** the crop is an instance option on this VLC build; the runtime call is
the only per-file route and may be a no-op on some builds (the toast still shows
the choice). If it does nothing on the Aiwa, tell me and we go the two-instance
route.

### 2. Guide: the selected channel always has an orange ring

The programme cell can be clipped by the left edge of the window (channel 6 was),
and the old 80 px rule then suppressed the gold focus entirely. Now the selected
channel's **own cell** carries a 3 px gold ring, and a clipped programme cell is
still highlighted down to 40 px wide.

### 3. Boot footer

Version is 24 px (was 28) at y=438, i.e. a 5 px gap under the TV/BROWSER chips;
at the old position its ascent overlapped the buttons and its descent ran past
the tube's visible bottom.

### 4. Watermark

8 px lower (`WATERMARK_BOTTOM = 450`) and 60 % opacity (was 85 %), as requested.

**Tests:** `test_display.py` **8** (aspect/crop cycling, legacy files, path
keys), `test_timeline.py` 38, the rest unchanged; offscreen `MainWindow` run
33/33. **Not verified on the Aiwa.**

## v0.7.2 — the ad-restart loop fixed, and the measured CRT safe area

Baseline: v0.7.1.

### 1. “The same ad restarts every few seconds” (Drama TV)

The log showed the tell: `Seek to 11s did not settle … (player at 5.4s)`, then
`Seek to 30s`, `43s`, `56s` — the join target grew by one ad length every round.

What happened: the player fell behind (a 13 s ad, a slow seek), so by the time
the timeline moved on, the next segment was *already over*. The app still played
it and seeked to `position_at(now)`, which is past the end of the file — a seek
that can never land. The cover then waited its full 12 s deadline, which put the
player even further behind, and the next round started 13 s deeper. Repeat.

Fixed in three places:
* `timeline.airing_at_or_after()` walks forward from the current airing until one
  is still running (used by the tick and by `_on_media_ended`); the player can no
  longer be asked to join a slot that ended.
* `_play_current()` refuses to seek without a trusted length (an unprobed ad used
  to be seeked to `target/1800` of the file — 0.6 % — and never moved) and clamps
  a target at/past the end instead of seeking past EOF.
* `_on_media_ended()` always advances at least one segment, so a file that ends a
  little early cannot replay its own tail in a loop.

### 2. CRT safe area, measured from the user’s red box

On the calibration photo the red line sits at **x 21–24 / 689–692, y 0–2 /
449–452** — so the tube shows almost the whole raster, much more than the old
72…652 / 48…431 guess. The measured box (inner edges, 4 px inset) is now one
constant in `screens/base.py`: **28…684 × 8…444**, and everything that was
outside it moved inside:

| element | before | now |
|---|---|---|
| channel OSD | right 640, top 54 | right 672, top 20 (the real corner) |
| watermark | left 24, bottom 458 | left 30, bottom 442 (was cut by the tube) |
| library progress bar | raster bottom (420…480) | 384…444 |
| guide hint bar | 422…452 | 414…442 |
| guide grid / NOW line | to 422 | to 440 |
| menu porthole | x 438…696 | x 426…684 |
| menu notice | 422…448 | 412…438 |
| boot version | baseline 440 | 432 |
| browser / picker hint | 430…452 / 450…474 | 410…432 / 412…436 |

**Tests:** `test_timeline.py` **38** (adds the late-jump walk), the rest unchanged
(12/19/15/20/11), offscreen `MainWindow` run 29/29. **Not verified on the Aiwa.**

## v0.7.1 — guide cells fixed, per-file aspect, seasonal + daypart folders

Baseline: v0.7.0.

### 1. The guide's programmes are stretched again

v0.7.0's `programme_blocks()` scanned a fixed 6 h back and stopped at a block
cap. On channels with short programmes the cap was reached *before* the window,
so the list ended early and the guide drew two cells and then nothing (the
“squished” grid in the screenshots). It now walks **back to the start of the
programme that contains the window** and builds forward from there — no fixed
look-back, no cap before the window, and the block containing “now” always
starts at its real time. Regression test added
(`test_blocks_fill_the_window_for_short_programmes`).

### 2. Volume OSD is centred

`VOL 65` + bar now sit in the middle of the bottom edge instead of the right
corner.

### 3. Per-file aspect override (the “2.21:1” commercials)

The crop is an instance option (16:10, cannot change per file on this VLC
build), but the **display aspect** can. `scripts/display.py` keeps a map of
`file → aspect` in `display_overrides.json`, and a new hotkey — **A** by default,
rebindable in SETTINGS → HOTKEYS — cycles `AUTO → 16:9 → 4:3 → 2.21:1 → 1.85:1
→ 16:10` for the file on screen, applies it live and remembers it. A green
`ASPECT 2.21:1 WIDE` toast confirms it. So the two awkward commercials can be set
once and will play correctly forever, and everything else stays 16:10.

### 4. Seasonal and time-of-day folders

Folders inside a channel now tag what is in them; no config file needed.

| folder (anywhere under the channel) | effect |
|---|---|
| `Commercials/Christmas/` (`Xmas`, `Holiday`) | those ads only 1 Dec → 6 Jan |
| `Commercials/Halloween/` | only 1 Oct → 2 Nov |
| `Commercials/Summer/` | only 1 Jun → 31 Aug |
| `Commercials/Morning/` (`Breakfast`) | only 05:00–11:00 |
| `Commercials/Late Night/` (`Overnight`, `Night`) | only 23:00–05:00 |
| `Morning/` (programmes) | that window plays them first |
| `Late Night/` (programmes) | same, at night |

Seasonal ads are mixed into every pod while in season. A channel with *any*
daypart folder switches from the free-running cycle to a **day of windows**:
00–05 late night, 05–11 morning, 11–23 main, 23–24 late night, each with its own
cycle built from the programmes and ads that belong to it, anchored at the
clock time. A programme never runs past the end of its window. Channels without
daypart folders keep the existing cycle untouched.

**Tests:** `test_timeline.py` **35** (day windows, seasonal pools, programme
boundaries, folder tagging, plus everything from v0.7.0), `test_cover_wait` 12,
`test_window_state` 19, `test_playlist` 15, `test_schedule` 20, `test_probe` 11.
Offscreen `MainWindow` run: 25/25. **Not verified with real VLC or the Aiwa.**

## v0.7.0 — a real broadcast timeline, a guide that tells the truth, settings

Baseline: v0.6.5. This release answers the second round of bug notes; several of
them were the same root cause, so the player, the guide and the guide preview now
share **one** source of truth (`scripts/timeline.py`).

### 1. Kawaii TV's frame of a clip — the two remaining paths

v0.6.5 fixed the live tuning cover, but two things still showed a stale frame:

* **the guide preview** (`preview.py`) had no cover at all: it started a second
  player into the little 160×110 window and seeked it 400 ms later, so frame 0
  of a 1.2 GB MPEG-PS was on screen until the seek landed. The native video
  widget is now **hidden** until the preview player reports the join position
  (`ChannelPreview.is_ready()`); the panel shows the channel number and `TUNING`
  in the meantime. Browsing channels in the guide no longer flashes the
  *previous* channel either, because the widget is hidden the moment the target
  changes;
* **changing back to a channel** could still lift the cover on the old clip's
  clock: right after `set_media()`, `get_time()` still belongs to the previous
  media, which can look like “at target”. The cover now waits for
  `MediaPlayerPlaying` (`VlcPlayer.started`) before it evaluates anything, and a
  second condition was added: `CoverWait.min_hold_s`, a settle window that scales
  with the file size (≈0.25 s for an MP4, ≈1.1 s for a 1.2 GB captures).

### 2. Ads are part of the schedule now (this fixes several reports)

Every channel has a **cycle** built from its programmes and its ad pods: breaks
at fixed points inside long programmes, a pod between programmes, the ads chosen
by a seeded RNG keyed on `(channel, programme, pod)`. Tuning joins whatever the
timeline airs at that second — programme *or* commercial.

That means:

* **“ads get interrupted when I switch channel and come back”** — confirmed, and
  fixed. Before, the schedule only knew about programme time, so leaving during
  a break threw the rest of the pod away and dropped you further into the
  programme. Now the pod occupies its wall-clock slot: come back and you are
  wherever the channel really is (possibly in the next commercial).
* **the guide is accurate** — it reads the same cycle, so the title under “now”
  is the title on screen;
* **channels break at different times** — the interval is per channel (a
  deterministic ±2 min shift), and `catalog/<CHANNEL>/channel.json` can override
  it: `{"ad_every_min": 7, "ad_min": 2, "ad_max": 4}` (negative = no mid-rolls).
* **pause** freezes the picture but not the broadcast; resuming more than 20 s
  behind live rejoins the timeline (with the black cover), like changing channel
  back to it. It does not stretch or skip the ads.

`_check_midroll` / `_start_midroll` / `_end_midroll` and the queue-index
bookkeeping are gone; a 1 s `_live_tick` keeps the picture on the timeline (it
also handles a programme that overruns its slot, and a broken file: the tick
moves on instead of dropping to boot).

### 3. TV guide: real listings, and 24–72 h of time travel

* the fake `mock_schedule_for_channel` (9:30a / 10:00a / 10:30a, repeating the
  channel's videos) is gone; cells come from the timeline with real start/end
  times, real titles, and ad time inside the programme slot (the guide lists
  **programmes only**, as asked);
* **LEFT / RIGHT slide the window** half an hour at a time, up to **72 hours**
  ahead — the early-cable-box horizon — and never back past the present;
* the header, the info plate and the day column use the app clock (Today /
  Tomorrow / weekday), and a red **NOW** line marks the present in the graph;
* selecting a channel shows what it airs at the window, `ENTER` watches it live.

### 4. SETTINGS screen (M > SETTINGS) — clock, hotkeys, volume, ads

* **CLOCK** — VCR-style: enter to edit, up/down switches hour/minute, left/right
  changes it. The offset is saved in `settings.json`, and the guide, the schedule
  and the OSD all read it (`scripts/clock.py`). Setting the clock forward moves
  the whole broadcast day, which is also how you test dayparts;
* **TIME FORMAT** — 24-hour / 12-hour readouts;
* **COMMERCIALS** — on/off (rebuilds every timeline);
* **AUDIO LEVELING** — VLC's `normvol` filter, the “level programmes against
  commercials” switch (instance option, so it applies on the next launch);
* **VOLUME** — the output level, with a new **volume OSD** (bottom-right, green
  bar) and global `+` / `-` keys that work on every screen;
* **HOTKEYS** — rebind any action (up/down/left/right/select/back/pause/guide/
  menu/info/library/picker/volume) to any key: enter, press the key, done. Stored
  in `settings.json`, loaded at startup;
* **ABOUT** — version and channel count.

### 5. The porthole is the user's GIF, and the menu is reachable everywhere

* `assets/ui/porthole.gif` (the green wireframe globe) plays inside the silver
  rim, clipped to the ellipse; the channel number that used to sit on top of it
  is gone;
* **M** opens the menu from boot, guide, browser and live (it used to work only
  on Live), and BACK returns to the screen you came from;
* THEMES / ABOUT now say something instead of doing nothing.

### 6. “Some ads don't have the 19:10 ratio”

No code change; the explanation is in `HANDOVER_v0_7_0.md` §5. Short version:
`VlcPlayer` crops **every** file to 16:10 at instance level, so a 4:3 ad loses
~17 % of its height, a 16:9 ad loses a little width, and an ad with baked-in
letterbox bars keeps them — the crop cannot remove black that is part of the
picture. Fixing it per file needs the container probe's width/height (already
available) plus a display-mode decision; that is the next step, not a bug in the
current ratio.

**Tests:** `test_timeline.py` **25** (tiling, mid-rolls, tail guard, pods,
per-channel policy, offsets, blocks, determinism, duration learning),
`test_cover_wait.py` 12, `test_window_state.py` 19, `test_playlist.py` 15 (the
legacy queue helpers are still covered), `test_schedule.py` 20, `test_probe.py`
11. Offscreen run of the real `MainWindow` (`scratch/smoke_v070.py`, 25 checks):
timeline tuning, cover gating on `MediaPlayerPlaying`, tick advance, guide
blocks + scrolling + horizon, settings, hotkey rebind, menu GIF, per-channel
policy. **Not verified with real VLC or on the Aiwa.**

## v0.6.5 — the Kawaii TV flash, green channel numbers, a window you can move

Baseline: v0.6.4. Three user reports, one of them a real playback bug.

### 1. “Only Kawaii TV shows one frame of a clip for a second after the static”

**Cause.** The tuning snow was lifted on a stopwatch: the seek gave up after a flat 3.5 s and a
`QTimer.singleShot(4000)` released the cover regardless. `get_time()` reaching the join position
only proves the *demuxer* got there — the video output can still be holding the previous picture.
The Kawaii TV captures are 44-minute MPEG-PS files whose seeks take seconds (the 1.2 GB file the
older handover measured), so the snow went away mid-seek and a stale frame sat on screen until the
seek landed and playback started. MP4 channels seek in milliseconds, which is why only that
channel showed it.

**Fix — the cover now waits for a picture, not for a clock** (`scripts/cover_wait.py`, new):

* release only when the position is at the target **and** the clock advanced on two consecutive
  100 ms polls (≈200 ms of decoded playback), which a frozen vout cannot fake;
* a join at 0:00 has no seek, so it waits until the new media has actually played 0.35 s;
* a corrective seek that moves the position away restarts the confirmation;
* hard cap raised 3.5 s → **12 s**, and if it is hit the log says why (seek never settled, or the
  clock is frozen); nothing can leave the screen covered forever;
* the snow now only *bursts* for 1.1 s; if the file is still not ready the cover turns **black** and
  holds (endless snow reads as "broken", black reads as "changing channel" — and the green OSD is
  still on top, so it looks like a set with no signal yet);
* **audio is ducked while covered** — the same artefact was audible: the first second of the episode
  at the wrong position, then the jump;
* one restartable `_snow_guard` QTimer replaces the two `QTimer.singleShot(4000)` calls (the
  overlapping-timer bug noted in the v0.6.4 review, §4-1: a stale shot could cut the *next* cover
  short).

### 2. Green channel-number OSD

Every channel change now flashes its number the way a CRT/cable box did: **Bedstead at 80 px**
(8 font pixels on the 10-row grid, antialiasing off), `#33FF33` with a 2 px black outline, top-right
inside the safe box (right edge 640, top 54), held 4 s then faded over ~5 frames. It is drawn *above*
the tuning snow, so the number is on screen while the picture is still rolling, and it is cleared in
library mode. `LiveScreen.show_channel_osd()` / `_paint_channel_osd()`, called from
`tune_to_channel()`.

### 3. The window can be dragged anywhere

Borderless at 720×480, so there was never a title bar to grab; on the 1440p monitor it sat wherever
Windows put it. Now:

* drag with the left button from **anywhere**, including over the video. The picture is a native
  libvlc child window, so presses over it never reach Qt — `VideoOverlay` (the transparent window
  that already sits above the picture) now forwards them, and it is no longer click-through. Nothing
  in the app used the mouse, so nothing else changed;
* a click also brings the app forward (`raise_` + `activateWindow`), because the overlay itself
  cannot take focus — the keyboard has to stay on the main window;
* the position is saved **per screen** in `window_state.json` (`scripts/window_state.py`), so the
  Aiwa and the desktop monitor each keep their spot; the file is clamped into the screen at startup
  (a resolution change cannot leave it half off the edge), and a monitor being plugged in or removed
  moves a lost window back onto a real screen;
* the 720×480 raster, the VLC binding, the overlay tracking and the CRT behaviour are untouched —
  the overlay follows on every move event, so the watermark and OSD stay glued to the picture;
* open-hand cursor over the picture as the only affordance (no title bar to hint with).

**Tests:** `test_cover_wait.py` **12** (slow seek, frozen vout, join at 0:00, corrective seek,
late tolerance, hard deadline), `test_window_state.py` **19** (clamp, per-screen restore, missing
screen, corrupt file, visibility). Existing suites unchanged: `test_playlist` 15, `test_schedule`
20 (+3 skipped without ffprobe), `test_probe` 11. Offscreen run of the real `MainWindow` with a
fake player: cover held for 4 s of seeking, lifted when the clock advanced, volume restored, OSD
fades, overlay drag press/move/release forwarded. **Not verified with real VLC or on the Aiwa.**

## v0.6.4 — heavier commercial breaks, done properly

Baseline: v0.6.3. The `app.py` the user sent back for review was byte-identical to the
v0.6.3 one (12 min / 1-2 ads), so the requested policy is applied here.

**Policy (all in `app.py`, all overridable by environment variable)**

| setting | value | override |
|---|---|---|
| mid-roll interval | 10 min | `NULLA_AD_BREAK_MINUTES` (0 = off) |
| min video length for mid-roll | 20 min | — |
| ads per break | 5-10 | `NULLA_AD_MIN`, `NULLA_AD_MAX` |
| tail guard | 90 s | — |

**Fixes**
* **Between-video breaks ignored the new range.** `tune_to_channel` hard-coded
  `build_playlist(min_ads=1, max_ads=2)`, so only mid-rolls would have become 5-10 ads. Both
  kinds of break now use `AD_BREAK_MIN_ADS` / `AD_BREAK_MAX_ADS`.
* **A bad commercial could throw you to the boot screen.** `_advance_after_failure()` counted a
  failed ad as a failed *channel* item; once every ad of a break had failed (queue = the break) it
  aborted playback. Inside a break it now skips just that ad and carries on.
* **Frame-0 flash when the show resumes after a break** (the video is reloaded and seeked back).
  With a break every 10 minutes that would flash the start of the episode 6x an hour. The resume
  is now covered by a short **black** cover released when the seek lands
  (`RESUME_COVER_BLACK = False` = use tuning snow instead). `LiveScreen.begin_tune(black=...)`.
* **Same ad closing one break and opening the next.** `build_ad_break(avoid_first_id=...)`.
* **Breaks now sit at fixed points in the show** (10:00, 20:00, 30:00 ...) via
  `playlist.next_break_position()` instead of "10 min after you tuned in", so a channel breaks at
  the same moments however you join; never closer than 60 s after joining.
* `check_commercials.py` reports the real policy and warns when a channel's ad pool is smaller than
  the break size (every break would replay the same few ads).

**Tests:** `test_playlist.py` 15 (was 8) — 5-10 ad breaks, small pools, no repeated opener,
fixed break positions; `test_schedule.py` synthetic clips now clear the 120 kbps plausibility
floor (23/23); `test_probe.py` unchanged (11). Break-failure / resume-cover logic checked against a
fake player. Offscreen smoke test of the real `MainWindow`: policy values and black/snow cover.

Not verified here: playback on Windows with real VLC and the Aiwa.

## v0.6.3 — watermark on the user's blue box; user assets respected

### Watermark position
Taken straight from the box the user drew on a screenshot (a 672×449 capture of
the 720×480 raster), mapped up by 720/672 and 480/449:

| | screenshot | raster |
|---|---|---|
| box left | 22 | **24** |
| box bottom | 431 | **461** |
| box size | 128×82 | 137×88 |

The logo's bottom-left corner now sits on that box's bottom-left corner:
`WATERMARK_LEFT = 24`, `WATERMARK_BOTTOM = 458` (3 px above the mapped box bottom
so nothing clips). Every channel logo is 80 px tall after scaling, so they all sit
at **(24, 378..458)** — 24 px from the left edge, 22 px from the bottom.

This replaces the safe-area maths from v0.6.1/0.6.2 (72 + 10, 431 − margin): the
user's own box wins. `SAFE_*` constants are kept for reference only.

### User assets — do not touch
These two files are now the user's own artwork, shipped **byte-for-byte**:

| file | size | note |
|---|---|---|
| `assets/ui/boot_logo.png` | 965×930, 1 014 235 B | raw artboard, **not dithered** — do not run it through `tools/make_boot_logo.py`, do not replace it |
| `assets/ui/library_bg.png` | 720×480, 24 122 B | the blue CD background, replaces the old red texture |

`boot.py` was not touched at all (320×316 logo, TUNE IN, MEDIA EXPLORER, chips at
378, version at 440 — the user's layout).

Verified: selftest 7/7, logo correlation **1.00** at (24, 378), −0.14 at the old
(82, 341).

## v0.6.2 — channel watermark 7 px lower

Feedback on v0.6.1: the watermark sat "a bit too high up". It is now 7 px closer
to the bottom edge — still inside the yellow safe box.

* `LiveScreen.WATERMARK_BOTTOM_MARGIN = 3` (was 10, same as the left margin).
  For a 120×80 logo that puts it at **x 82, y 348..428** — i.e. 3 px above the
  safe line (431) and 52 px above the tube edge, instead of 341..421.
* The position is now produced by **one** function,
  `LiveScreen.watermark_origin(logo_h)`, used by the painter *and* by
  `tools/selftest_ui.py`. The check had already drifted once in v0.6.1 (it was
  still looking at the pre-v0.6.1 coordinates), so it can no longer disagree
  with what is drawn.
* `tools/selftest_ui.py`: before each screenshot the app is pushed into the
  Windows topmost band and the overlay is re-raised above it. A screen capture
  of the window rect was picking up whatever window happened to be on top
  (that is why some earlier test shots showed an editor instead of the video).

Verified: 7/7 selftest checks, logo correlation **1.00** at the new origin,
−0.10 at the old one.

## v0.6.1 — 16:10 picture, watermark inside the yellow box, scrolling library titles

Baseline: the user's v0.6.0. Only the three requested things changed (boot
screen, logo size, live bar, VLC logo options untouched).

### 16:10 crop + 16:10 aspect for every video
Why: 640×480 content sat in ~90 columns of black pillars on the Aiwa.

Measured on this machine (VLC 3.0.20) — only one mechanism actually works:

| attempt | result |
|---|---|
| `:crop=16:10` as a media option | parsed as a **16×10 pixel** box → extreme zoom |
| `video_set_crop_geometry("16:10")` | accepted, no effect |
| `:aspect-ratio=16:10` as a media option | no effect at all |
| **`--video-filter=crop --crop=16:10` at instance level** | **real crop** — verified on a CJK overlay: glyph proportions stay correct (a plain aspect change stretched them wide) |
| **`video_set_aspect_ratio("16:10")` at runtime** | **works** (media option does not) |

Implementation: `VlcPlayer(video_widget, crop=...)` puts the crop filter on the
instance; `play_item()` calls `video_set_aspect_ratio()` at 0 / 350 / 1200 ms
(the vout may still be starting when `play()` returns). Policy lives in
`app.VIDEO_ASPECT` / `app.VIDEO_CROP`; the guide's "Movie 16:10" label follows it.

Result: black columns **90 → 5**; 15 px bars top/bottom, which fall inside the
CRT's overscan (the yellow safe box starts at y 48).

### Channel watermark moved inside the safe box
It was 10 px from the *screen* edge — i.e. inside the overscan — so the left and
bottom of the logo were being cut. Now placed inside the measured yellow box
(x 72..652, y 48..431) with a 10 px margin → **(82, 431 − 10 − height)**.
Verified: logo correlation **1.00** at the new spot, **−0.10** at the old one.

### Library titles scroll when they don't fit
The selected row's title now scrolls like a ticker: 1.2 s still, then 42 px/s to
the left, repeating with a 72 px gap. Clipped to the title column so it never
runs under the weekday/date, and the timer stops when the screen is hidden.
Rows that already fit (and all non-selected rows) render exactly as before.

Files: `scripts/vlc_player.py`, `scripts/app.py`, `scripts/screens/live.py`,
`scripts/screens/browser.py`, `scripts/screens/guide.py` (label), `scripts/version.py`.

## v0.6.0 — commercials actually play (incl. one-video channels)

**Reported:** an episode ends and the next starts with no commercial break.

**What was really happening** (measured, not guessed):

```
AKIHABARA TV : 8 main, 22 ads  -> queue MaMaaMaaMaa…   ads DO play
MTV_RETRO    : 1 main, 51 ads  -> queue "M"            zero ads, ever
```

`build_playlist()` only inserts a break *between* two main videos and skips the
last one, so:

1. a channel whose only video is 4 hours long never reached "between videos" —
   MTV played four hours of tape with no commercial at all;
2. at the loop point of a multi-video channel (last → first) there was no break
   either.

### Fixes
* `tune_to_channel()` now builds the queue with **`insert_after_last=True`** —
  the last video is followed by a break, so the loop point has one too, and a
  one-video channel gets `M a a` instead of `M`.
* **Mid-roll breaks** (`app._check_midroll`): a main video longer than 20 min is
  interrupted every 12 min by 1-2 ads from its own channel pool, then **resumes
  at the interrupted position** (verified: interrupted at 599 s → resumed at
  598.8 s). Driven by the player position, so pausing/seeking can't spam ads,
  and guarded by `current_src()` so the old media can't trigger a break.
* `playlist.build_ad_break()` — the mid-roll pool logic lives next to
  `build_playlist()` instead of being duplicated.
* `scripts/check_commercials.py` (new) — prints per channel: main count, pool
  size, the built queue pattern (`M` / `a`), and warns when a channel would play
  with no commercials.
* `scripts/test_playlist.py` (new) — 8 tests, including “single video still gets
  ads” and “the queue breaks before looping”.

### Tuning
`NULLA_AD_BREAK_MINUTES` (default `12`, `0` = no mid-rolls), plus
`AD_BREAK_MIN_VIDEO_S`, `AD_BREAK_TAIL_GUARD_S`, `AD_BREAK_MIN/MAX_ADS` at the top
of `app.py`. Nothing else was touched — boot screen, logo, live bar and VLC
options are unchanged.

## v0.5.5 — boot art at 2x: full-bleed

"2x viewing size" on a 4:3 raster can only be done by cropping — a square art
shown twice as large (696×670) does not fit 720×480. So the collage is now the
whole screen:

* **720×480 full-bleed**, drawn 1:1 — **2.07× the width** of the v0.5.4 logo
  (348 → 720). Cropped to the 4:3 aspect around the centre, which keeps the TV,
  the woman, the parrot and the statue; the CD and film strip lose their tails
  behind the bottom bar.
* Same asset treatment as every other background: `dither grid 360×240, Bayer
  4×4, 6 levels, 2× nearest` → 2×2 px cells, 53 KB.
* `python tools/make_boot_logo.py --cover 720x480 --out assets/ui/boot_art.png`
  regenerates it; `--anchor top` keeps the parrot instead of centring.
* The mode chips needed help over the art: a navy scrim gradient
  (`CHIPS_TOP-34 .. +40`, alpha 0 → 228) plus a dark fill on the unselected
  chip — before this the white BROWSER outline vanished into the film strip.
* The version tag stays bottom-right, now on that scrim.
* `assets/ui/boot_logo.png` (348×334) is kept as the fallback if `boot_art.png`
  is missing.

## v0.5.4 — boot logo at the size the safe area can give

"Make it larger" — done by removing what was stealing height, not by breaking
the safe area.

* Logo **284×272 → 348×334** (+57 % area, +23 % linear vs v0.5.3; it is now
  1.9× the original v0.5.2 art). Still 1:1, still the 2×2-cell dither.
* `TUNE IN:` is **off by default** (`BootScreen.SHOW_HEADER = False`) — its
  26 px + gap went to the logo.
* The version tag moved from a centred line under the chips to the
  **bottom-right corner** of the safe box, so it costs no vertical space.

| element | y |
|---|---|
| logo (348×334) | 48..382 |
| TV / BROWSER chips | 390..424 |
| version (right aligned) | 402..422 |

Everything is still inside the measured yellow box (x 72..652, y 48..431).
To trade back: `SHOW_HEADER = True`, `LOGO_BOX_H = 300`
(`python tools/make_boot_logo.py --height 300`).

## v0.5.3 — boot logo sized and dithered for the CRT safe area

The user supplied a 720×480 CRT calibration (yellow box = what the Aiwa
actually shows: **x 72..652, y 48..431**; the green/blue lines below get eaten
by overscan, and 1 px detail flickers in 480i).

### Logo
* **Bigger:** 232×224 → **284×272** (+48 % area) — the most that fits the safe
  area while keeping TUNE IN, the mode chips and the version line.
* **Dithered like the rest of the UI:** new `tools/make_boot_logo.py` runs the
  same pipeline as `build_ui_assets.py` — half-resolution ordered dither
  (Bayer 4×4, 6 levels per channel) then 2× nearest-neighbour, so every dither
  cell is a **2×2 px block** and cannot flicker. Alpha is dithered too
  (4 levels) so the art's drop shadow does not become a hard jagged edge.
  Result: 118 unique colours instead of 140 571, 14 KB instead of 709 KB.
* **Drawn 1:1** — never scaled at runtime, otherwise the baked dither pattern
  would smear back into 1 px noise.

### Layout inside the safe area
Every element is now inside y 48..431 (was: header at y 34 and the footer at
y 452, i.e. both outside the safe area):

| element | y |
|---|---|
| TUNE IN: (26 px) | 48..74 |
| logo (284×272) | 82..354 |
| TV / BROWSER chips (34 px) | 362..396 |
| version (20 px) | 408..428 |

* "MEDIA EXPLORER" was **dropped**: the safe area only has room for one of
  {big logo, subtitle} and the logo won. To bring it back, shrink `LOGO_BOX_H`
  by ~44 and draw a 30 px line at y 366.
* Sizes moved into `BootScreen` constants (`HEADER_BASELINE`, `LOGO_TOP`,
  `LOGO_BOX_W/H`, `CHIPS_TOP`, `FOOTER_BASELINE`) so the layout can be re-tuned
  without hunting through paint code.

### Verification
`python tools/selftest_ui.py --catalog G:\nullaOS\catalog` → 7/7. Boot shot at
`tools/selftest_out/0_boot.png`.

## v0.5.2 — boot logo artboard, version footer, watermark legibility

### Boot screen
* The cream pill + `nullaOS` wordmark + TV badge is **replaced by the media
  collage artboard** (`assets/ui/boot_logo.png`, the user's "Artboard 1.png").
  It keeps its transparency, is trimmed to its content, and is scaled **with
  the aspect ratio locked** into a 240×224 box (`BootScreen.LOGO_TOP/W/H`) —
  never stretched. If the asset is missing, the screen falls back to a plain
  wordmark instead of an empty hole.
* `WINTER 2026` is gone: the footer now prints **the version number** ("v0.5.2").

### One place for the version
* `scripts/version.py` (new) holds `APP_NAME` / `APP_VERSION`. The window title
  and the boot-screen footer both read it, so a release only needs that one
  line changed (plus `CHANGELOG.md`). **Every variation must bump it.**

### Channel watermark was unreadable on bright pictures
Measured while verifying the guide: the MTV logo at 55 % opacity disappeared
over a near-white frame (pattern correlation 0.19 — i.e. barely there). It is
now drawn at **85 % with a 2 px black drop shadow** (the shadow is generated
once from the logo's own alpha). Correlation on the same frame went to 1.00.

## v0.5.1 — guide: live preview panel + channel cells that don't collide

### The guide's top-right panel is a live picture now
It used to show the channel logo — which says nothing about what is on. It now
shows the channel itself, **joined at the position it would be at on the wall
clock**, so the guide is a real "what's on now" window.

* `scripts/preview.py` (new) — a second, muted `libvlc.MediaPlayer` rendered
  into its own native child widget (the one rendering path that is known to
  work on this machine). It is stopped whenever the guide is not on screen and
  re-aimed when the cursor moves; the same channel is not reloaded (no black
  flash when moving away and back).
* `guide.py` — the panel draws the frame, a red **LIVE** dot and
  `LIVE 01 AKI`, and keeps the number as a fallback if the preview cannot
  play (no VLC / missing files).
* Opened from the guide with G; the preview follows Up/Down.

### "Numbers overlap the names"
In the channel column the code drew the logo, then the channel number **and**
the abbreviation into the same 24 px band — `01` and `AKI` printed right on top
of each other (that is the screenshot the user sent). Now:

* channel with a logo → logo on top, **number below it, nothing else**
  (the logo already is the name)
* channel without a logo → number and abbreviation stacked with no overlap
* the info plate's programme title is elided with `…` instead of being cut
  mid-glyph.

### Verification
`python tools/selftest_ui.py --catalog G:\nullaOS\catalog` → **7/7**, including
the new `7_guide_preview` check (preview area has real picture content, 485
distinct colours). Screenshots land in `tools/selftest_out/`.

## v0.5.0 — logo, mid-broadcast join, durations, tuning snow, bar fade

Everything below was verified on the target machine (VLC 3.0.20, Python 3.15,
PySide6 6.12, the real `G:\nullaOS\catalog`) by driving the app and looking at
the screenshots — not by reading the docs.

### Channel logo (the long-standing "watermark never appears")
**Root cause, measured:** libvlc accepts every logo call and renders nothing.
`--sub-source=logo` + `video_set_logo_string/int` → no pixels. `:logo-file=`
media options → no pixels. The same for `--vout=d3d11|d3d9|gl|directdraw|wingdi`.
A nested-window check explained the second half: libvlc creates its own
`VLC video main` window *and* a `VLC video output` child inside the video
widget, so a Qt child widget (even with `WA_NativeWindow`) is covered — only a
20 px sliver outside VLC's client area was visible.

**Fix:** `scripts/overlay.py` — a frameless, translucent, click-through,
always-on-top window tracking the video rect. Measured: 96 % pixel coverage
over the playing video, never takes focus, 720×480 repaint in ~0.6 ms.
The logo, the progress bar, PAUSED and the info card are all painted there now.

### "Channel shows the beginning, then jumps"
**Root cause, measured:** `get_length()` is wrong for the 44-minute MPEG-PS
capture (134 013 s ≈ 37 h). The old code turned a target time into a position
fraction by dividing by that number, so a 43-minute join became a 1.1 % seek →
the player landed near the start and then crawled.
`set_time(900000)` on that file lands at **20 s**; `:start-time=1500` lands at
**30 s**; `set_position(0.5)` lands at **1344 s** (exactly half of the real
2680 s). So:

* `:start-time` is gone from `play_item()`.
* Seeking is `set_position(fraction)` + a *trusted* duration
  (`ScheduleState.known_duration`), verified closed-loop against `get_time()`
  (real seconds) and `get_position()` (fraction of the real duration), with one
  proportional correction if the first attempt misses.
* The tuning snow stays up until that check passes (max 3.5 s, then it shows
  the picture anyway rather than leaving the screen covered).
* Measured result: AKIHABARA joins at 43:16 with **1 seek** and ~1.3 s of snow;
  MTV in ~1.0 s (it used to be a fixed 2 s of static *plus* a visible flash).

### Durations without ffprobe
`scripts/probe.py` (new, stdlib only) reads the container header:
mp4/mov/m4v (mvhd + sample-entry dimensions), mkv/webm (EBML Info), avi (avih),
mpeg-ps (PES PTS span). Every candidate goes through `plausible()` (bitrate
window), and the filename hint (`44′40`, `44分40秒`, `1h02m33s`, `01:02:33`) is
consulted *before* libvlc because libvlc lies about at least one file here.

* `duration_probe.py` order is now: container → ffprobe (if installed) →
  filename hint → libvlc-if-plausible.
* `app._learn_current_duration()` refuses implausible libvlc lengths, so
  `schedule_state.json` can't be poisoned again
  (log: `Ignoring libvlc length 134014s … keeping the probed length`).
* `scripts/test_probe.py` — 11 tests, all pass, no ffmpeg/Qt/VLC needed.
* `fix_durations.py` rewritten: repairs a poisoned cache from the real files
  (`--dry-run` supported). `diagnose_durations.py` now prints
  container vs libvlc vs cache per video and flags mismatches.

### Tuning snow is 4:3
`assets/ui/tv_static.mp4` is really 720×480 — but its *picture* is letterboxed
inside that frame (measured: the top 30 rows are pure black). The screen is now
covered by generated full-frame snow (240×160 noise upscaled nearest-neighbour,
plus a rolling hum bar and tearing lines), so it fills the CRT edge to edge.
The mp4 is still in `assets/` but no longer used.

### Progress bar
* Fades in/out (~330 ms, `_animate_bar`/`_tick_bar_anim`) instead of snapping.
* Long titles use `QFontMetrics.elidedText()` in the space the time readout
  leaves — they end in `…` instead of being cut mid-glyph.
* Total time comes from the probed file length, so switching from a 4-hour
  video to a 1-hour one no longer shows the previous total.
* The video widget is no longer resized to make room: the bar is an overlay on
  the bottom 60 px of the picture (a real OSD), which removed a whole class of
  geometry bugs.

### Also fixed on the way
* The DDR info card (I) was painted *behind* the video, so it never showed.
  It is on the overlay now, and its values are readable — the old code faded a
  `CompositionMode_Plus` glow rectangle over them, producing a solid green blob.
* PAUSED was drawn twice (VLC marquee + text); it is overlay-only now, white on
  a dark plate.
* `vlc_player.py`: dead logo plumbing, `:start-time`, and a stale-length window
  after `set_media()` (it made the bar show the previous media's length).

**Delete `schedule_state.json` once after upgrading** — or run
`python scripts/fix_durations.py`, which repairs it from the files.

## v0.3.4 — live-TV schedule fix

**Root cause of the "channel jumps around / advances 4x-47x" bug:** a channel's position is
`(now - start_time) % total_length_of_all_its_videos`. `total_length` started at a 30-minute
guess per video and was silently replaced by the real length each time VLC reported one, so
every update moved the join point to a different video. (Reproduced with a simulated clock.)

* `schedule_state.py` — every length change / file added, removed or reordered now re-anchors
  `start_time`, so whatever is airing right now keeps airing at the same offset. After that it is
  plain wall-clock again. Probe-verified lengths are *locked*; lengths < 1 s / NaN are ignored;
  `VideoItem.duration` from the catalog is honoured; the first-run start offset uses `zlib.crc32`
  (Python's `hash()` changed it every launch); the state file is written atomically.
* `duration_probe.py` — real lengths via ffprobe (fallback: libvlc parse) at startup in the
  background, plus a quick synchronous probe of the channel you are tuning to.
* `app.py` — a length is only learned if VLC's reported length belongs to the *main* file that is
  playing (not an ad / the previous clip); seeks are verified and retried (libvlc ignores
  `set_position` until the stream is seekable); stale pending seeks are cleared; one `Schedule:`
  log line per tune shows elapsed / total / video / position for debugging.
* `vlc_player.py` — `current_src()` so callers can verify what VLC is playing.
* `test_schedule.py` — `python scripts/test_schedule.py` (no Qt/VLC needed; 23 checks).
