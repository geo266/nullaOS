# Drop your test video MP4 files here.
#
# Per-channel subfolders will be auto-created by test_pattern.py:
#   assets/mock/videos/moviewave/ep1.mp4
#   assets/mock/videos/moviewave/ep2.mp4
#   assets/mock/videos/toonzone/ep1.mp4
#   assets/mock/videos/jptv/ep1.mp4
#   assets/mock/videos/vhsarchive/ep1.mp4
#   ...
#
# To use your own files instead of the SMPTE test patterns:
#   1. Drop your MP4s at the matching paths
#   2. Edit assets/mock/catalog.json to update titles/durations
#   3. Set deinterlace mode per channel:
#        "none"     — modern progressive MP4s (24/30p)
#        "ivtc"     — telecined DVD rips (24p-in-30p)
#        "yadif2x"  — interlaced VHS rips (60fps, very CRT-authentic)
