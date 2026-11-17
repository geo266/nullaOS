# Drop your channel folders here.

# The app auto-detects this folder on launch — no `--catalog` flag needed.
# If this folder contains channel subfolders, the app uses them INSTEAD of
# the mock JSON at assets/mock/catalog.json. If this folder is empty (or
# missing), the app falls back to the mock JSON.

# Convention (matches MediaWave2000):
#   nullaOS/catalog/
#   ├─ MOVIE WAVE/              <- folder name = channel name
#   │  ├─ Breaker Night.mp4      <- main content (any video filename)
#   │  ├─ Lazer Dogs.mp4
#   │  ├─ Commercials/           <- per-channel commercial pool (ISOLATED)
#   │  │  ├─ Coke Ad.mp4
#   │  │  └─ Cereal Ad.mp4
#   │  └─ Logos/                 <- optional channel logo
#   │     └─ logo.png
#   ├─ JP TV/
#   │  ├─ Anime Ep 1.mp4
#   │  └─ Commercials/
#   │     ├─ Suntory.mp4         <- Japanese commercials, never cross-pollinate
#   │     └─ Uniqlo.mp4
#   └─ Library/                  <- optional, for Browser mode (on-demand)
#      ├─ Movies/
#      │  ├─ Big Buck Bunny.mp4
#      │  └─ Big Buck Bunny.cover.png  <- cover alongside the movie
#      └─ TV Shows/
#         └─ Seinfeld/
#            ├─ S01E01.mp4
#            ├─ S01E02.mp4
#            └─ cover.png            <- show poster

# Auto-detected per channel:
#   - Channel number: sequential by sorted folder name
#   - Channel abbrev: first 3 alphanumeric chars (JP TV -> JPT)
#   - Channel color: deterministic hash of folder name -> 8-color palette
#   - Channel logo:   <channel>/Logos/logo.png (optional)
#   - Commercials:    <channel>/Commercials/*.mp4 (strict per-channel pool)

# To override defaults (deinterlace mode, aspect, desc) — TODO v2.1:
#   Drop a channel.json in the channel folder with:
#     {"deinterlace": "yadif2x", "aspect": "4:3", "desc": "Anime, 24h"}
