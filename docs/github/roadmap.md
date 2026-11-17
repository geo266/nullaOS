# Roadmap

Four iterations of two weeks, plus the three items that shipped in v0.7.7. This is
the same list as [`project-items-import.csv`](project-items-import.csv), with the
reasoning that the CSV has no room for.

## Iteration 1 — make the repository honest

**Catalogue: one bad file must not take a channel down.** The failure mode that
hurts most on a CRT: a single truncated capture and the channel simply is not
there, with nothing on screen to say why. Skip it, log it once, keep going.

**Banner: fall back to a channel description.** The banner's fourth line is empty
whenever the video has no `.txt` beside it, which is most of them. A channel-level
blurb in `channel.json` costs one key and makes the bar useful on every channel.

**CI on push.** Six test modules and the offscreen window harness already exist;
they just are not run by anything but a human. windows-latest, Qt offscreen, a
stubbed `vlc` — the harness already proves this works.

**Move the screenshot generator into `tools/`.** Right now the README images come
from a script that is not in the repository, which means they cannot be
regenerated or trusted.

## Iteration 2 — the parts a viewer notices

**Dayparts you can see.** The pools exist and work; the screen says nothing about
them. A viewer should be able to tell that the Christmas reels are in season and
that the 02:00 slot draws from a different pool.

**A settings schema version.** Small, boring, and it prevents the class of bug
where a renamed key silently reverts someone's clock offset.

**A 3-hour guide.** Ninety minutes is one and a half screens of grid. Three hours
is a real EPG, but it needs a column count that survives long titles — measure
first, then choose.

**Banner hold as a setting.** Six seconds is right on a 20" tube and long on a
monitor. It is one constant away from being a preference.

## Iteration 3 — the parts a user notices

**Untrusted durations, made visible.** `probe.py` already decides when a duration
can be trusted. Saying so on the grid turns a mystery into an explanation.

**Profiles.** Two people share one CRT. Today they share one settings file and one
schedule.

**Channel flick repeat rate.** Holding Up on the Aiwa's converter scrolls faster
than the eye can follow. Qt's default repeat is the wrong default here.

**A tune summary in the log.** One line per join makes an evening of odd
behaviour diagnosable without a photograph of the screen.

## Iteration 4 — the long tail

**The Windows-only overlay, written down.** The transparent-window trick is the
least obvious part of the codebase and the first thing a contributor will trip
over. Document it, and fail with a readable message rather than a black screen.

**A licence.** "All rights reserved" contradicts a project about preservation.
MIT or GPL-3.0 both fit; it is the author's call.

**The `.txt` blurb convention.** One line in the catalog README would save every
future user the guesswork.

## Not planned

* software CRT effects (scanlines, bloom, curvature) — the tube does that;
* a built-in downloader or scraper — it plays what you already have;
* a web UI — the point is the box under the television.
