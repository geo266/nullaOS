"""
test_schedule.py — standalone tests for the live-TV schedule (no Qt, no VLC).
Run from the project root:   python scripts/test_schedule.py
Uses a simulated clock; the ffprobe test is skipped if ffmpeg/ffprobe aren't on PATH.
"""
import os, subprocess, sys, tempfile, shutil
from pathlib import Path
from types import SimpleNamespace as V

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import schedule_state as S                    # noqa: E402
from scripts.duration_probe import probe_duration_seconds, probe_channel, have_ffprobe  # noqa: E402

CLOCK = [1_800_000_000.0]
S.time.time = lambda: CLOCK[0]
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond: passed += 1; print(f"  PASS  {name}")
    else:    failed += 1; print(f"  FAIL  {name}  {detail}")


def vids(n=4, dur=0.0): return [V(id=f"v{i}", src=f"v{i}.mp4", duration=dur) for i in range(n)]
def fresh(airing_for=4246.0):
    st = S.ScheduleState(); st.get_or_init("ch").start_time = CLOCK[0] - airing_for; return st
def at(st, v): i, p = st.compute_live_position("ch", v); return i, p
def same(a, b, tol=1.0): return a[0] == b[0] and abs(a[1] - b[1]) <= tol


print("1. wall-clock advances 1:1")
v = vids(); st = fresh(); a = at(st, v); CLOCK[0] += 30; b = at(st, v)
check("+30 s of wall-clock = +30 s of position", b[0] == a[0] and abs((b[1] - a[1]) - 30) < 0.01, f"{a}->{b}")

print("2. learning real lengths never makes the channel jump (the v0.3.3 bug)")
v = vids(); st = fresh(); before = at(st, v)
for vid, d in zip(["v0", "v1", "v2", "v3"], [600, 2400, 900, 5000]):
    st.set_duration("ch", vid, d)
    check(f"after learning {vid}={d}s still airing the same video/offset", same(at(st, v), before), f"{before}->{at(st, v)}")
CLOCK[0] += 100; after = at(st, v)
check("then advances 1:1 again", after[0] == before[0] and abs(after[1] - before[1] - 100) < 0.01 or after[0] == before[0] + 1, f"{before}->{after}")

print("3. probe-locked lengths can't be overwritten by player-reported lengths")
st = fresh(); v = vids(); at(st, v)
st.set_duration("ch", "v1", 2400, source="probe")
check("probe accepted & locked", st.is_locked("ch", "v1") and st.get_duration("ch", "v1") == 2400)
changed = st.set_duration("ch", "v1", 15, source="play")        # e.g. VLC reported an AD's length
check("bogus play-time length rejected", (not changed) and st.get_duration("ch", "v1") == 2400)
check("sub-second garbage ignored", st.set_duration("ch", "v2", 0.2) is False)
check("NaN ignored", st.set_duration("ch", "v2", float("nan")) is False)

print("4. catalog changes (add / remove / reorder) keep the airing video airing")
v = vids(); st = fresh(); [st.set_duration("ch", f"v{i}", d, source="probe") for i, d in enumerate([600, 2400, 900, 5000])]
before = at(st, v); airing_id = v[before[0]].id
v2 = v + [V(id="new", src="new.mp4", duration=1234.0)]
r = at(st, v2)
check("append a file", v2[r[0]].id == airing_id and abs(r[1] - before[1]) <= 1.0, f"{airing_id} {r}")
v3 = list(reversed(v2)); r = at(st, v3)
check("reverse the order", v3[r[0]].id == airing_id and abs(r[1] - before[1]) <= 1.0, f"{v3[r[0]].id} {r}")
v4 = [x for x in v3 if x.id != airing_id]; r = at(st, v4)
check("remove the airing file -> still returns a valid index", 0 <= r[0] < len(v4) and r[1] >= 0)

print("5. catalog-provided durations are used instead of the 30-min default")
st = S.ScheduleState(); v = [V(id="a", src="a", duration=100.0), V(id="b", src="b", duration=200.0)]
at(st, v); check("durations seeded from VideoItem.duration", st.get_duration("ch", "a") == 100 and st.get_duration("ch", "b") == 200)

print("6. persistence + 'app closed for an hour'")
v = vids(); st = fresh(); [st.set_duration("ch", f"v{i}", d, source="probe") for i, d in enumerate([600, 2400, 900, 5000])]
before = at(st, v); tmp = Path(tempfile.mkdtemp()) / "schedule_state.json"; st.save(tmp)
st2 = S.ScheduleState.load(tmp); check("round-trip identical", same(at(st2, v), before))
CLOCK[0] += 3600; total = 8900; expected_cum = (sum([600, 2400, 900, 5000][:before[0]]) + before[1] + 3600) % total
i, p = at(st2, v); got_cum = sum([600, 2400, 900, 5000][:i]) + p
check("channel kept 'airing' while the app was closed (+3600 s)", abs(got_cum - expected_cum) < 0.01, f"{got_cum} vs {expected_cum}")
check("locked flags survive save/load", st2.is_locked("ch", "v0"))
tmp.write_text('{"channels": {"x": {"start_time": 5, "position_seconds": 99, "durations": {"a": -3}}}}')
st3 = S.ScheduleState.load(tmp); check("old/garbage state file loads without crashing", "x" in st3.channels and not st3.channels["x"].durations)

print("7. start offset is stable across processes (hash() was not)")
outs = {subprocess.run([sys.executable, "-c", "import sys;sys.path.insert(0,r'%s');from scripts.schedule_state import ScheduleState as S;print(round(S._initial_offset('ch-jptv'),3))" % ROOT],
        capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": str(seed)}).stdout.strip() for seed in (1, 2, 3)}
check("same offset for 3 different hash seeds", len(outs) == 1, str(outs))

print("8. different channels start at different points")
a = S.ScheduleState._initial_offset("ch-jptv"); b = S.ScheduleState._initial_offset("ch-moviewave")
check("offsets differ per channel", abs(a - b) > 1)

print("9. real ffprobe on generated clips")
if have_ffprobe() and shutil.which("ffmpeg"):
    d = Path(tempfile.mkdtemp()); clips = []
    for n, secs in (("a", 3), ("b", 5)):
        f = d / f"{n}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=duration={secs}:size=320x240:rate=10", "-vf", "noise=alls=60:allf=t", "-b:v", "600k", "-pix_fmt", "yuv420p", str(f)], check=True)
        clips.append(V(id=n, src=str(f), duration=0.0))
    got = [probe_duration_seconds(c.src, allow_vlc=False) for c in clips]
    check("ffprobe reads 3 s and 5 s clips", abs(got[0] - 3) < 0.3 and abs(got[1] - 5) < 0.3, str(got))
    st = S.ScheduleState(); ch = V(id="ch", videos=clips)
    at(st, clips); n = probe_channel(st, ch)
    check("probe_channel locks both", n == 2 and st.is_locked("ch", "a") and st.is_locked("ch", "b"))
    check("missing file -> 0.0, no crash", probe_duration_seconds(str(d / "nope.mp4"), allow_vlc=False) == 0.0)
else:
    print("  SKIP  ffprobe not on PATH")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
