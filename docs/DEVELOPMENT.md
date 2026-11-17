# How nullaOS gets built

This is the short version of the development process — how a change is decided,
built, checked and released. The bug-by-bug detail lives in
[CHANGELOG.md](../CHANGELOG.md); this page is about the method and the plan.

## The shape of the project

nullaOS is a 720×480 window with a video player behind it and a hand-painted
overlay above it. Everything the user sees is drawn by a `Screen` subclass in
`scripts/screens/` at exactly 720×480 pixels — no layout engine, no scaling, no
DPI. That decision costs some convenience and buys the only thing that matters
here: at 720×480 on a CRT, what is drawn is what appears.

Three rules held through every version:

1. **The catalogue is folders.** No database, no import step, no metadata cache
   the user has to maintain. If a channel folder is there, the channel exists.
2. **One source of truth for time.** `scripts/timeline.py` answers both "what is
   on now" and "what does the guide list". If the guide, the banner and the
   player could disagree, they eventually would.
3. **No software CRT effects.** The tube does the scanlines, the bloom and the
   wobble. The app supplies a 720×480 4:3 signal and gets out of the way; the
   only "effect" is the noise frame during a tune, because a real tuner shows
   one.

## The loop

Most versions were built in the same five steps.

**1. Watch it fail on the real hardware.** The Aiwa is the test rig, not a
monitor. Nearly every layout bug in this project was found there and nowhere
else: text clipping at the top of the tube, a watermark landing outside the
visible area, 1 px rules vanishing into phosphor bleed. The measured safe box in
`scripts/screens/base.py` (`SAFE_LEFT=28, SAFE_RIGHT=684, SAFE_TOP=8,
SAFE_BOTTOM=444`) is a photograph of that tube, and it is the only layout
authority in the codebase — screens lay themselves out inside it, they never
guess at margins.

**2. Reproduce it offscreen first.** Anything about timing, painting or state
gets a harness before it gets a fix. The pattern that proved itself: a
`QApplication` on `QT_QPA_PLATFORM=offscreen`, a stub `vlc` module, a fake player
that "loads" in a known 1.2 s, a temporary catalog, then drive the real
`MainWindow` and assert on what it did. `scratch/smoke_v070.py` runs 41 such
checks; `scratch/sim_transitions.py` fast-forwards 90 broadcast minutes through
the real window and reports every join, offset and skip.

**3. Fix the cause, not the symptom.** The clearest example is v0.7.7. The
symptom was "ads flash for a second and jump". The cause was three layers down:
the 1 s timeline tick returned early while a seek was settling, so it ran late;
each late tick pushed the next join deeper into its slot; after a pod of short
ads, joins landed inside the last second and were clamped. Fixing the visible
clamp would have hidden it. Removing the tick's dependency on the seek settled
it. Every entry in the CHANGELOG is written in that order — symptom, cause, fix —
because that is the only part worth keeping.

**4. Prove it with numbers.** A fix ships with a test that fails before it. The
tick bug got `TickLoopTests` (40 simulated minutes, join offset must stay under
3 s) and a boundary test for `next_after()`; the banner got checks for its
content, its paint order and its toggle; the layout work got pixel assertions
against the safe box. Current suites:

| suite | count | covers |
|---|---|---|
| `scripts/test_timeline.py` | 42 | schedule construction, joins, pods, dayparts, the tick loop |
| `scripts/test_display.py` | 8 | aspect/crop overrides, persistence |
| `scripts/test_cover_wait.py` | 12 | when the tuning cover may drop |
| `scripts/test_window_state.py` | 19 | remembered window position per monitor |
| `scripts/test_playlist.py` | 15 | library ordering, covers, progress |
| `scripts/test_probe.py` | 11 | ffprobe duration parsing and trust rules |
| `scratch/smoke_v070.py` | 41 | the real window, offscreen, end to end |

**5. Look at it.** A screenshot before shipping, at 720×480, over real picture
rather than over black. Two of the worst bugs in this project (a banner covering
the watermark, a bar cropped by the tube's overscan) were invisible in the code
and obvious in a still.

## Iterations

The version numbers are honest about scope: a `0.6.x` is layout and playback
furniture, a `0.7.x` is scheduling.

| build | the thing that changed |
|---|---|
| **0.5.0** | mid-broadcast join, real durations, tuning snow, the boot logo and the first painted chrome |
| **0.5.1–0.5.5** | the guide's live preview panel; boot art sized, dithered and full-bleed |
| **0.6.0** | commercials actually play — including channels with a single video |
| **0.6.1–0.6.3** | 16:10 picture, watermark inside the measured safe box, the user's own assets respected |
| **0.6.4** | heavier, better-shaped commercial breaks |
| **0.6.5** | the last "one frame of the clip" flashes; green channel numbers; a window you can drag |
| **0.7.0** | the real broadcast timeline, a guide that reads it, settings (clock, 12/24 h, ads, keys) |
| **0.7.1** | guide cells that fill the grid, per-file aspect, seasonal and daypart pools |
| **0.7.2** | the ad-restart loop; the measured CRT safe area |
| **0.7.3–0.7.5** | crop hotkey, selection ring, softer watermark, a guide that behaves like an EPG again |
| **0.7.6** | ad durations are probed and learned instead of assumed to be 30 s |
| **0.7.7** | the channel banner; the tick that was suppressed by a settling seek |

## Where it goes next

Kept here so the repository's issues have a spine. Roughly in order:

1. **A catalogue that survives a bad file.** One unreadable capture should log a
   line and be skipped, never take a channel down with it.
2. **Dayparts you can see.** The pools work; there is no UI that shows which
   window a channel is in or which ads it will draw from.
3. **A real settings file version.** `settings.json` has no schema version, so a
   rename means a silently ignored key.
4. **The guide at 3 hours.** It is a 90-minute window now; a longer window needs
   column widths that survive 20-character titles.
5. **Profiles.** Two people, two catalogues, one CRT — a `--profile` flag that
   switches `settings.json` and schedule state together.
6. **A capture checklist.** The banner's blurb comes from a `.txt` beside the
   video; nothing documents that convention except the catalog README.

## Credit

Built by geo266, with an AI pair doing the typing. The timeline model, the screen
geometry and the CRT calibration are human decisions; the test harnesses, the
simulations and a good deal of the stubbornness are the collaboration.
