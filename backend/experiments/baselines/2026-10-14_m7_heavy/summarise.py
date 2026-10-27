"""Held-out result against TARGETS.md: corridor vs reactive, paired by seed (run from anywhere)."""
import json
import math
import pathlib
import statistics as st

T95 = {9: 2.262, 10: 2.262}  # t for n-1 = 9 (n = 10)
HERE = pathlib.Path(__file__).parent / "results"


def interval(xs):
    m = st.fmean(xs)
    h = 2.262 * st.stdev(xs) / math.sqrt(len(xs))
    return m, m - h, m + h


for level in ("heavy", "medium"):
    by = {}
    for line in (HERE / f"{level}.jsonl").read_text().splitlines():
        if line.startswith("{"):
            r = json.loads(line)
            by.setdefault(r["seed"], {})[r["arm"]] = r
    pairs = [(d["reactive"], d["corridor"]) for d in by.values() if len(d) == 2]
    ev = [c["ev_duration_s"] - r["ev_duration_s"] for r, c in pairs]
    loss = [c["ev_time_loss_s"] - r["ev_time_loss_s"] for r, c in pairs]
    stops = [c["ev_stops"] - r["ev_stops"] for r, c in pairs]
    pdel = [(c["person_delay_s"] / r["person_delay_s"] - 1) * 100 for r, c in pairs]
    viol = sum(r["interlock_violations"] + c["interlock_violations"] for r, c in pairs)
    print(f"\n{level}: {len(pairs)} paired seeds; means reactive / corridor: "
          f"EV {st.fmean(r['ev_duration_s'] for r, _ in pairs):.0f} / {st.fmean(c['ev_duration_s'] for _, c in pairs):.0f} s, "
          f"stops {st.fmean(r['ev_stops'] for r, _ in pairs):.1f} / {st.fmean(c['ev_stops'] for _, c in pairs):.1f}")
    for name, xs, unit in (("EV travel time", ev, "s"), ("EV time lost", loss, "s"),
                           ("EV stops", stops, ""), ("person-delay", pdel, "%")):
        m, lo, hi = interval(xs)
        print(f"  {name}: {m:+.1f}{unit} [{lo:+.1f}, {hi:+.1f}]  per seed {[round(x) for x in xs]}")
    print(f"  interlock violations: {viol}")
    if level == "heavy":
        print("  H1", "pass" if interval(ev)[2] < 0 else "FAIL",
              "| H2", "pass" if interval(stops)[1] <= 0 else "FAIL",
              "| H3", "pass" if interval(pdel)[1] <= 0 else "FAIL",
              "| H4", "pass" if viol == 0 else "FAIL")
