# Publishing nullaOS to GitHub

The folder this file sits in (`github_release/nullaOS`) is a clean,
already-public-safe copy: no catalogue media, no per-install state, no
`reference/` art, no handover notes, no absolute paths from the author's machine.

Nothing on this machine has GitHub credentials, so the push has to be done once
from your side. It is four commands.

## 1. Create the repository

On github.com: **New repository** → name `nullaOS` → **Public** → do **not** add a
README, .gitignore or licence (they already exist here).

Suggested About text (the field next to the repo name):

> A 720×480 cable-box simulator for a real CRT. PySide6 + libVLC.

Topics: `pyside6` `libvlc` `crt` `retro` `broadcast` `epg` `media-player`
`windows` `python` `analog-video`

## 2. Push this folder

```powershell
cd path\to\github_release\nullaOS
git init -b main
git add .
git commit -m "nullaOS v0.7.7: channel banner, broadcast timeline, CRT-native UI"
git remote add origin https://github.com/geo266/nullaOS.git
git push -u origin main
```

If you have GitHub CLI installed and signed in, step 1 collapses into:

```powershell
gh repo create geo266/nullaOS --public --source . --remote origin --push `
  --description "A 720x480 cable-box simulator for a real CRT. PySide6 + libVLC."
```

## 3. Cut the release

```powershell
gh release create v0.7.7 --title "v0.7.7 — channel banner" --notes-from-tag
```

or attach `nullaOS_v0_7_7.zip` to a release by hand on the Releases page. Tag
naming: `v0.7.7`, one tag per build.

## 4. Fill the project board

Your board: <https://github.com/users/geo266/projects/2>

Create these fields first (Project → ⋯ → Settings → Custom fields):

| field | type | values |
|---|---|---|
| Status | single select | `Todo`, `In progress`, `Done` (default names) |
| Iteration | iteration | 2 weeks, starting the Monday after you import |
| Area | single select | `timeline`, `ui`, `catalog`, `playback`, `settings`, `docs`, `tools` |
| Size | single select | `S`, `M`, `L` |

Then **Project → ⋯ → Import items → CSV** and pick
[`project-items-import.csv`](project-items-import.csv). It carries 16 items:
three already shipped in v0.7.7 (marked `Done`), the rest spread across four
two-week iterations. Column names must match the field names above; if GitHub
complains about a column, delete it and import the rest — the Title and Body are
the part that matters.

The same list in prose, with the reasoning, is in
[`roadmap.md`](roadmap.md).

## What is deliberately not in this repository

* the `catalog/` media (copyright, size, and none of it is source);
* `reference/` (third-party art used as layout reference while building);
* `HANDOVER_*.md` (internal notes with local paths and one person's setup);
* `settings.json`, `window_state.json`, `schedule_state.json`,
  `display_overrides.json` (per-install state);
* `assets/ui/tv_static.mp4` (obsolete since snow is drawn procedurally — 20 MB).

One asset does need a decision before you go public: `assets/ui/boot_art.png` is
the boot collage and is built from found images. It is your artwork to publish or
replace; if you would rather not, swap it for a flat colour frame and the boot
screen still renders.
