"""Score the held-out run against TARGETS.md. usage: python summarise.py [results dir]"""
import glob
import json
import random
import statistics as st
import sys
from pathlib import Path

d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "results"
R: dict = {}
for f in glob.glob(str(d / "*.json")):
    r = json.load(open(f))
    R.setdefault(r["arm"], {})[r["seed"]] = r["summary"]
seeds = sorted(set.intersection(*(set(v) for v in R.values())))


def boot(xs, n=10_000):
    rng = random.Random(0)
    ms = sorted(st.fmean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return st.fmean(xs), ms[int(0.025 * n)], ms[int(0.975 * n) - 1]


def pct(a, b, key):
    return [100 * (R[b][s][key] / R[a][s][key] - 1) for s in seeds]


print(f"seeds {seeds[0]}-{seeds[-1]}, n={len(seeds)}\n")
print("| arm | EV time s (4 EVs) | time lost s | stops | stopped s | person-delay | violations | EVs done |")
print("|---|---|---|---|---|---|---|---|")
for arm in ("reactive", "reactive_lane", "corridor", "corridor_lane"):
    xs = [R[arm][s] for s in seeds]
    print(f"| {arm} | {st.fmean(x['ev_duration_s'] for x in xs):.0f} | "
          f"{st.fmean(x['ev_time_loss_s'] for x in xs):.0f} | {st.fmean(x['ev_stops'] for x in xs):.1f} | "
          f"{st.fmean(x['ev_waiting_time_s'] for x in xs):.0f} | "
          f"{st.fmean(x['person_delay_s'] for x in xs):.0f} | {sum(x['interlock_violations'] for x in xs)} | "
          f"{sum(x['n_ev_completed'] for x in xs)}/{4 * len(xs)} |")
print()
rows = [("H1", "reactive", "reactive_lane", "ev_duration_s", "ev"),
        ("H2", "corridor", "corridor_lane", "ev_duration_s", "ev"),
        ("H3", "reactive", "reactive_lane", "person_delay_s", "pd"),
        ("H4", "corridor", "corridor_lane", "person_delay_s", "pd"),
        ("D1", "reactive_lane", "corridor_lane", "ev_duration_s", "none"),
        ("D1b", "reactive_lane", "corridor_lane", "person_delay_s", "none"),
        ("-", "reactive", "corridor", "ev_duration_s", "none")]
print("| id | comparison | metric | mean % [95 % CI] | verdict |")
print("|---|---|---|---|---|")
for hid, a, b, key, kind in rows:
    m, lo, hi = boot(pct(a, b, key))
    if kind == "ev":
        v = "PASS" if (m <= -3 and hi < 0) else "FAIL"
    elif kind == "pd":
        v = "PASS" if hi <= 3 else "FAIL"
    else:
        v = "–"
    print(f"| {hid} | {b} vs {a} | {key} | {m:+.1f} [{lo:+.1f}, {hi:+.1f}] | {v} |")
ok = all(R[a][s]["interlock_violations"] == 0 and R[a][s]["n_ev_completed"] == 4
         for a in ("reactive_lane", "corridor_lane") for s in seeds)
print(f"\nH5 (_lane arms: 0 violations, all EVs complete): {'PASS' if ok else 'FAIL'}")
