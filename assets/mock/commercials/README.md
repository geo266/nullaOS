# Per-channel commercial pool subfolders live here.
#
# STRICT isolation — the spec is that each channel uses ONLY its own
# commercial subfolder. The Japanese channel uses Japanese ads; USA
# channels use USA ads. They never cross-pollinate (the playlist
# builder draws from channel.commercials only).
#
# Subfolder layout:
#   assets/mock/commercials/moviewave/ad1.mp4  <- USA commercials
#   assets/mock/commercials/moviewave/ad2.mp4
#   assets/mock/commercials/toonzone/ad1.mp4
#   assets/mock/commercials/jptv/ad1.mp4       <- Japanese commercials (different pool)
#   assets/mock/commercials/vhsarchive/ad1.mp4
#
# To verify the isolation after running test_pattern.py, tune to JP TV
# and watch the [AD] overlays — they should always say "JP:" and
# never "USA:".
