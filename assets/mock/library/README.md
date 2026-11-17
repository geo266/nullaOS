# On-demand library for Browser mode.
#
# Layout (matches catalog.json "library" section):
#   assets/mock/library/movies/<file>.mp4          <- flat movie files
#   assets/mock/library/shows/<show-id>/<file>.mp4 <- episode files grouped by show
#
# Library plays items on-demand WITHOUT commercial injection — that's the
# whole point of Browser mode. Use it for your movies and TV shows when
# you want to pick what to watch instead of channel-surfing.
#
# Drop your own MP4s at these paths (or rename in catalog.json to match
# your filenames). test_pattern.py will fill in SMPTE bars at the same
# paths if you haven't supplied your own files yet.
