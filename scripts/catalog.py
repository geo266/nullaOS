"""
catalog.py — Mock catalog loader for PROJECT:CRT

Loads a JSON catalog that simulates the folder structure:
    MyCatalog/
    ├─ ChannelA/             <- channel folder
    │  ├─ video1.mp4         <- main content
    │  ├─ video2.mp4
    │  └─ Commercials/       <- per-channel commercial pool
    │     ├─ ad1.mp4
    │     └─ ad2.mp4
    ├─ ChannelB/
    │  ├─ ...
    │  └─ Commercials/
    └─ ...

For v1 we read from assets/mock/catalog.json. v2 will add scan_real_folder()
which walks the filesystem using os.walk() and produces the same shape.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("catalog")

# ── Auxiliary folder detection ──────────────────────────────────────────────
# Ported from MediaWave2000's CATALOG_AUXILIARY_FOLDER_NAMES (channelsurfer2000.py).
# Any folder with one of these normalized names is treated as a commercial pool,
# NOT as a channel in itself.

CATALOG_AUXILIARY_FOLDER_NAMES = {
    "commercials", "commercial", "ads", "adverts", "advertisements",
    "bumpers", "promos", "station ids", "station id", "idents", "ids",
}

# ── Special pools (v0.7.1) ──────────────────────────────────────────────────
# A folder name inside a channel (or inside its Commercials/ folder) tags the
# files in it.  Two kinds:
#   * dayparts — used only at that time of day (programmes *and* ads);
#   * seasons  — used only during that part of the year (ads; programmes too if
#     someone wants a Christmas special folder).
# Anything unrecognised is ignored: the files just behave as normal videos/ads.
#
# Times are local hours, end exclusive, wrapped at midnight (23 → 5).
DAYPART_FOLDERS = {
    "morning":     (5, 11),
    "breakfast":   (5, 11),
    "afternoon":   (11, 17),
    "evening":     (17, 23),
    "prime time":  (19, 23),
    "primetime":   (19, 23),
    "late night":  (23, 5),
    "overnight":   (23, 5),
    "night":       (21, 5),
}

#: month/day ranges, inclusive start, exclusive end (wrapping over new year).
SEASON_FOLDERS = {
    "christmas": ((12, 1), (1, 7)),
    "xmas":      ((12, 1), (1, 7)),
    "holiday":   ((12, 1), (1, 7)),
    "halloween": ((10, 1), (11, 3)),
    "summer":    ((6, 1), (9, 1)),
}


def _normalise_folder(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


def daypart_for_folder(name: str) -> str:
    """'Late Night' -> 'late_night', or '' when it is not a daypart folder."""
    key = _normalise_folder(name)
    if key in DAYPART_FOLDERS:
        return key.replace(" ", "_")
    return ""


def season_for_folder(name: str) -> str:
    key = _normalise_folder(name)
    return key if key in SEASON_FOLDERS else ""


def season_active(season: str, when) -> bool:
    """True when `when` (a datetime) is inside the season's window."""
    rng = SEASON_FOLDERS.get(_normalise_folder(season))
    if not rng:
        return False
    (sm, sd), (em, ed) = rng
    md = (when.month, when.day)
    if (sm, sd) <= (em, ed):
        return (sm, sd) <= md < (em, ed)
    return md >= (sm, sd) or md < (em, ed)   # wraps over New Year

# Video file extensions accepted as playable content (matches MediaWave2000).
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".mpg", ".mpeg", ".m4v", ".ts")


def is_auxiliary_folder(name: str) -> bool:
    """Return True if a folder name should be treated as a commercial pool,
    not as a channel. Mirrors MediaWave2000's is_catalog_auxiliary_folder_name()."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()
    return normalized in CATALOG_AUXILIARY_FOLDER_NAMES


def is_video_file(name: str) -> bool:
    return name.lower().endswith(VIDEO_EXTS)


# ── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class VideoItem:
    id: str
    title: str
    src: str          # path to the file (relative to project root or absolute)
    duration: float = 0.0  # seconds; 0 = unknown, will be probed at runtime
    # Browser-mode metadata (v0.3+). 'kind' = 'm' (movie, green ellipse indicator)
    # or 's' (show episode, gold square indicator). added_day/added_date are
    # for the TiVo-style list sort display. Optional — old catalogs without
    # these fields still load.
    kind: str = "m"               # "m" | "s"
    added_day: str = ""           # e.g. "Fri"
    added_date: str = ""          # e.g. "10/23"
    # v0.3.1: optional movie/show cover image (for Browser mode row thumbnail)
    cover: Optional[str] = None   # path to PNG, e.g. "assets/mock/library/covers/big_buck_bunny.png"
    # v0.3.7: optional per-video description + preview image
    # User drops a <video-stem>.txt (first line = short title, rest = description)
    # and <video-stem>.png alongside the video file. scan_real_folder detects them.
    description: str = ""         # short description shown in picker info panel
    preview: Optional[str] = None  # path to preview image shown in picker thumb tray
    # v0.7.1: special-pool tags, taken from the folder the file lives in.
    # daypart: "morning" | "afternoon" | "evening" | "late_night" | ...
    # season:  "christmas" | "halloween" | "summer" | ...
    daypart: str = ""
    season: str = ""


@dataclass
class Channel:
    id: str
    number: int
    name: str
    abbrev: str                    # short call-sign for guide grid cells
    color: str = "#FFB000"         # channel accent color (hex)
    logo: Optional[str] = None    # path to logo PNG
    deinterlace: str = "none"      # "none" | "yadif2x" | "yadif" | "ivtc" | "bob"
    aspect: str = "4:3"           # VLC --aspect-ratio (4:3, 16:9, etc.)
    thumb: Optional[str] = None   # path to channel thumbnail PNG (e.g. "assets/ui/thumb_0.png")
    desc: str = ""                # short description for picker screen ("Anime, 24h. Japanese ads only.")
    # v0.7.0: per-channel commercial policy, from <channel>/channel.json.
    # ad_every_min: 0 = use the app default, <0 = no mid-roll breaks, >0 = minutes.
    ad_every_min: float = 0.0
    ad_min: int = 0               # 0 = use the app default
    ad_max: int = 0
    videos: list[VideoItem] = field(default_factory=list)
    commercials: list[VideoItem] = field(default_factory=list)

    def __post_init__(self):
        # Tolerate JSON where videos/commercials are dicts not VideoItem yet.
        self.videos = [
            v if isinstance(v, VideoItem) else VideoItem(**v)
            for v in self.videos
        ]
        self.commercials = [
            c if isinstance(c, VideoItem) else VideoItem(**c)
            for c in self.commercials
        ]


@dataclass
class Show:
    """A TV show with multiple episodes. Used in the Library (Browser mode)."""
    id: str
    title: str
    episodes: list[VideoItem] = field(default_factory=list)
    # v0.3: TiVo-style list shows the show's added-day/date alongside episodes
    added_day: str = ""
    added_date: str = ""
    # v0.3.1: optional show poster image (shown in Browser mode row thumbnail)
    cover: Optional[str] = None

    def __post_init__(self):
        self.episodes = [
            e if isinstance(e, VideoItem) else VideoItem(**e)
            for e in self.episodes
        ]


@dataclass
class Library:
    """On-demand library for Browser mode. Plays without commercial injection.
    Movies are flat files; shows are folders with episodes."""
    movies: list[VideoItem] = field(default_factory=list)
    shows: list[Show] = field(default_factory=list)

    def __post_init__(self):
        self.movies = [
            m if isinstance(m, VideoItem) else VideoItem(**m)
            for m in self.movies
        ]
        self.shows = [
            s if isinstance(s, Show) else Show(**s)
            for s in self.shows
        ]

    def all_items(self) -> list[tuple[str, VideoItem]]:
        """Flatten the library into a list of (category, video) tuples,
        e.g. ("Movies", movie1), ("The Office", episode1).
        Used by the Browser screen to display a flat TiVo-style list.

        For show episodes, the episode VideoItem inherits the parent Show's
        added_day/added_date (since the prototype's LIB array treats every
        library row uniformly — the show's day/date is shown for each
        episode, not per-show).
        """
        import copy
        out: list[tuple[str, VideoItem]] = []
        for m in self.movies:
            out.append(("Movies", m))
        for s in self.shows:
            for e in s.episodes:
                # Clone so we don't mutate the catalog in place
                ep = copy.copy(e)
                if not ep.added_day:
                    ep.added_day = s.added_day
                if not ep.added_date:
                    ep.added_date = s.added_date
                # Show episodes get kind='s' from the JSON; if missing, default
                if not ep.kind:
                    ep.kind = "s"
                # v0.3.1: episodes inherit the parent show's cover if they
                # don't have their own
                if not ep.cover:
                    ep.cover = s.cover
                out.append((s.title, ep))
        return out


@dataclass
class Catalog:
    """Top-level catalog. Has two sides:
      - channels: TV mode (channel surfing with per-channel commercial injection)
      - library:   Browser mode (on-demand playback, no commercials)
    Both populated from the same JSON file."""
    root: str
    channels: list[Channel] = field(default_factory=list)
    library: Library = field(default_factory=Library)

    def __post_init__(self):
        # Tolerate library being passed as a dict
        if isinstance(self.library, dict):
            self.library = Library(**self.library)
        elif self.library is None:
            self.library = Library()


# ── Loader ───────────────────────────────────────────────────────────────────

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent.parent / "assets" / "mock" / "catalog.json"


def load_catalog(path: Path | str = DEFAULT_CATALOG_PATH) -> Catalog:
    """Load the mock catalog from JSON. Raises FileNotFoundError with a clear
    message if the file is missing (so the user knows to check the path)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Catalog file not found: {path}\n"
            "Drop your mock catalog.json at this path, or edit DEFAULT_CATALOG_PATH in catalog.py."
        )
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    channels = [Channel(**ch) for ch in data.get("channels", [])]
    # Strip underscore-prefixed comment fields before passing to dataclasses
    lib_data = {
        k: v for k, v in data.get("library", {"movies": [], "shows": []}).items()
        if not k.startswith("_")
    }
    library = Library(**lib_data)
    return Catalog(
        root=data.get("root", "MockTV/"),
        channels=channels,
        library=library,
    )


def find_channel_by_number(catalog: Catalog, number: int) -> Optional[Channel]:
    for ch in catalog.channels:
        if ch.number == number:
            return ch
    return None


def find_channel_by_id(catalog: Catalog, channel_id: str) -> Optional[Channel]:
    for ch in catalog.channels:
        if ch.id == channel_id:
            return ch
    return None


# ── v2: real folder scanner ─────────────────────────────────────────────────

# Palette for auto-assigning channel colors based on the channel name hash.
# These are the same saturated retro colors used in the mock catalog.
_CHANNEL_PALETTE = [
    "#FF9A5A",  # orange (MOVIE WAVE)
    "#FF0066",  # pink (JP TV)
    "#3FA9F5",  # blue (SITCOM 24)
    "#5CFF3A",  # green (PUBLIC ACCESS)
    "#FFB000",  # gold
    "#9C00FF",  # purple
    "#00B4FF",  # cyan
    "#E50000",  # red
]


def _color_for_channel_name(name: str) -> str:
    """Deterministic color assignment based on channel name hash.
    Same name → same color every run."""
    h = sum(ord(c) for c in name)
    return _CHANNEL_PALETTE[h % len(_CHANNEL_PALETTE)]


def scan_real_folder(root: Path | str) -> Catalog:
    """v2: walk a real folder structure and build a Catalog.

    Conventions (matching MediaWave2000):
      - Each top-level subfolder becomes a Channel (folder name = channel name)
        UNLESS the folder name is an auxiliary type (Commercials, Bumpers, etc.)
      - Inside each channel folder:
          - *.mp4 / *.mkv / *.avi / *.mov at any depth = main content
          - Commercials/ (or Bumpers/, Promos/, Ads/) subfolder = per-channel pool
          - Logos/logo.png = channel logo (optional)
      - A top-level "Library" folder (if present) is the on-demand library:
          - Library/Movies/*.mp4 = movie files
            (a *.cover.png alongside each movie is the cover image)
          - Library/TV Shows/<show-name>/*.mp4 = episodes
            (Library/TV Shows/<show-name>/cover.png = show poster)

    Args:
        root: Path to the catalog root folder.

    Returns:
        Catalog with channels + library populated.

    Raises:
        NotADirectoryError if root doesn't exist or isn't a directory.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    channels: list[Channel] = []

    # Distinguish the Library subfolder (handled separately) from channels
    library_dir = root / "Library"
    channel_dirs = sorted(
        p for p in root.iterdir()
        if p.is_dir()
        and p.name != "Library"
        and not is_auxiliary_folder(p.name)
        and not p.name.startswith(".")  # skip hidden folders (.DS_Store cruft, etc.)
    )

    for idx, channel_dir in enumerate(channel_dirs, start=1):
        videos: list[VideoItem] = []
        commercials: list[VideoItem] = []
        logo_path: Optional[str] = None

        # Per-channel metadata (v0.7.0): <channel>/channel.json
        meta: dict = {}
        meta_file = channel_dir / "channel.json"
        if meta_file.is_file():
            try:
                with meta_file.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    meta = loaded
            except Exception as e:
                log.warning("Ignoring %s (%s)", meta_file, e)

        def _num(key: str, default: float = 0.0) -> float:
            try:
                return float(meta.get(key, default) or default)
            except (TypeError, ValueError):
                return default

        # Detect channel logo: <channel-dir>/Logos/logo.png
        logos_subdir = channel_dir / "Logos"
        if logos_subdir.is_dir():
            for logo_name in ("logo.png", "logo.jpg", "logo.jpeg"):
                logo_file = logos_subdir / logo_name
                if logo_file.exists():
                    logo_path = str(logo_file)
                    break

        # Walk inside the channel folder
        for path in sorted(channel_dir.rglob("*")):
            if not path.is_file() or not is_video_file(path.name):
                continue
            # If any parent dir is auxiliary, classify as commercial
            rel_parts = path.relative_to(channel_dir).parts[:-1]
            aux_idx = next((i for i, part in enumerate(rel_parts)
                            if is_auxiliary_folder(part)), None)
            parent_aux = aux_idx is not None
            # Special pools (v0.7.1): a "Morning" / "Late Night" / "Christmas"
            # folder anywhere under the channel tags the file inside it.
            tags = rel_parts[aux_idx + 1:] if parent_aux else rel_parts
            daypart = ""
            season = ""
            for part in tags:
                daypart = daypart or daypart_for_folder(part)
                season = season or season_for_folder(part)
            # Look for description .txt + preview .png/.jpg alongside the video
            # Convention: <video-stem>.txt (first line = short title, rest = description)
            #             <video-stem>.png or <video-stem>.jpg (preview image)
            description = ""
            preview_path: Optional[str] = None
            txt_file = path.with_suffix(".txt")
            if txt_file.exists():
                try:
                    with txt_file.open("r", encoding="utf-8", errors="replace") as f:
                        description = f.read().strip()
                except Exception:
                    pass
            for ext in (".png", ".jpg", ".jpeg"):
                img_file = path.with_suffix(ext)
                if img_file.exists():
                    preview_path = str(img_file)
                    break
            item = VideoItem(
                id=path.stem,
                title=path.stem,
                src=str(path),
                duration=0.0,
                description=description,
                preview=preview_path,
                daypart=daypart,
                season=season,
            )
            if parent_aux:
                commercials.append(item)
            else:
                videos.append(item)

        if not videos and not commercials:
            continue  # empty channel folder — skip

        ch_name = channel_dir.name
        # Abbreviation = first 3 alphanumeric chars (spaces removed).
        # "JP TV" → "JPT", "MOVIE WAVE" → "MOV", "SITCOM 24" → "SIT"
        abbrev = "".join(c for c in ch_name.upper() if c.isalnum())[:3]
        channels.append(Channel(
            id=ch_name.lower().replace(" ", "-").replace("/", "-"),
            number=idx,
            name=ch_name.upper(),
            abbrev=abbrev,
            color=_color_for_channel_name(ch_name),
            logo=logo_path,
            deinterlace=str(meta.get("deinterlace", "none") or "none"),
            aspect=str(meta.get("aspect", "4:3") or "4:3"),
            ad_every_min=_num("ad_every_min"),
            ad_min=int(_num("ad_min")),
            ad_max=int(_num("ad_max")),
            videos=videos,
            commercials=commercials,
        ))

    # ── Library scan ──────────────────────────────────────────────────────
    library = Library()
    if library_dir.is_dir():
        # Movies: Library/Movies/<file>.mp4 + optional <file>.cover.png
        movies_dir = library_dir / "Movies"
        if movies_dir.is_dir():
            for movie_path in sorted(movies_dir.iterdir()):
                if not movie_path.is_file() or not is_video_file(movie_path.name):
                    continue
                # Look for cover alongside: <stem>.cover.png (or .jpg)
                cover: Optional[str] = None
                for ext in (".cover.png", ".cover.jpg", ".cover.jpeg",
                            "-cover.png", "-cover.jpg"):
                    cover_file = movies_dir / (movie_path.stem + ext)
                    if cover_file.exists():
                        cover = str(cover_file)
                        break
                # Look for description .txt + preview image alongside the movie
                movie_description = ""
                movie_preview: Optional[str] = None
                movie_txt = movie_path.with_suffix(".txt")
                if movie_txt.exists():
                    try:
                        with movie_txt.open("r", encoding="utf-8", errors="replace") as f:
                            movie_description = f.read().strip()
                    except Exception:
                        pass
                for ext in (".png", ".jpg", ".jpeg"):
                    img_file = movie_path.with_suffix(ext)
                    if img_file.exists():
                        movie_preview = str(img_file)
                        break
                library.movies.append(VideoItem(
                    id=movie_path.stem,
                    title=movie_path.stem,
                    src=str(movie_path),
                    duration=0.0,
                    kind="m",
                    cover=cover,
                    description=movie_description,
                    preview=movie_preview,
                ))

        # TV Shows: Library/TV Shows/<show-name>/<episode>.mp4
        shows_dir = library_dir / "TV Shows"
        if shows_dir.is_dir():
            for show_dir in sorted(p for p in shows_dir.iterdir() if p.is_dir()):
                episodes: list[VideoItem] = []
                show_cover: Optional[str] = None
                for path in sorted(show_dir.iterdir()):
                    if not path.is_file():
                        continue
                    if is_video_file(path.name):
                        episodes.append(VideoItem(
                            id=path.stem,
                            title=path.stem,
                            src=str(path),
                            duration=0.0,
                            kind="s",
                        ))
                    elif path.name.lower() in ("cover.png", "cover.jpg",
                                                 "poster.png", "poster.jpg"):
                        show_cover = str(path)
                if episodes:
                    library.shows.append(Show(
                        id=show_dir.name.lower().replace(" ", "-"),
                        title=show_dir.name,
                        episodes=episodes,
                        cover=show_cover,
                    ))

    return Catalog(root=str(root), channels=channels, library=library)


# ── CLI smoke test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    cat = load_catalog()
    print(f"Loaded catalog: {cat.root}")
    print(f"Channels: {len(cat.channels)}")
    for ch in cat.channels:
        print(f"  [{ch.number:02d}] {ch.name} ({ch.abbrev}) "
              f"— {len(ch.videos)} videos, {len(ch.commercials)} commercials "
              f"— deinterlace={ch.deinterlace}, aspect={ch.aspect}")
    print(f"\nLibrary: {len(cat.library.movies)} movies, {len(cat.library.shows)} shows")
    for m in cat.library.movies:
        print(f"  [MOVIE] {m.title}")
    for s in cat.library.shows:
        print(f"  [SHOW]  {s.title} — {len(s.episodes)} episodes")
