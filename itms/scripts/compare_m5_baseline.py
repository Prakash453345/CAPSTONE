"""Compare a new M5 benchmark run against the frozen baseline.

Paired per seed (same arm, level, seed), so run-to-run noise cancels.
Lower is better for delay / stops / waits / violations; higher for throughput.

Usage:
    python scripts/m5_baseline_benchmark.py --out /tmp/after.json
    python scripts/compare_m5_baseline.py \
        baselines/2026-09-16_m5_traffic_coordination/m5_baseline_results.json /tmp/after.json
"""

from __future__ import annotations

import json
import statistics as st
import sys

T_CRIT = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365,
          9: 2.306, 10: 2.262}
KEYS = [("person_delay_s", -1), ("stops_per_vehicle", -1),
        ("person_throughput_per_hour", +1), ("p95_wait_s", -1), ("max_wait_s", -1)]


def val(r: dict, key: str) -> float:
    if key == "p95_wait_s":
        return r["wait_time_s"]["p95_s"]
    if key == "max_wait_s":
        return r["wait_time_s"]["max_s"]
    return r[key]


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    base, new = (json.load(open(p)) for p in sys.argv[1:3])
    idx = lambda d: {(r["arm"], r["demand_level"], r["seed"]): r for r in d["records"]}  # noqa: E731
    b, n = idx(base), idx(new)
    common = sorted(set(b) & set(n))
    if not common:
        sys.exit("no overlapping (arm, level, seed) runs")
    groups = sorted({(a, lv) for a, lv, _ in common},
                    key=lambda g: ({"light": 0, "medium": 1, "heavy": 2}[g[1]], g[0]))

    print(f"{'level':7s} {'arm':8s} {'metric':27s} {'baseline':>12s} {'new':>12s} "
          f"{'change':>8s}  {'95% CI of diff':>26s}  verdict")
    print("-" * 115)
    regressions = 0
    for arm, lv in groups:
        seeds = [s for a, l2, s in common if a == arm and l2 == lv]
        for key, good in KEYS:
            bv = [val(b[(arm, lv, s)], key) for s in seeds]
            nv = [val(n[(arm, lv, s)], key) for s in seeds]
            diffs = [y - x for x, y in zip(bv, nv, strict=True)]
            mb, mn, md = st.fmean(bv), st.fmean(nv), st.fmean(diffs)
            pct = 100 * md / mb if mb else 0.0
            if len(diffs) > 1 and st.stdev(diffs) > 0:
                half = T_CRIT.get(len(diffs), 2.0) * st.stdev(diffs) / len(diffs) ** 0.5
                lo, hi = md - half, md + half
                sig = lo * hi > 0
            else:
                lo = hi = md
                sig = md != 0
            if not sig:
                verdict = "same" if md == 0 else "n.s."
            else:
                verdict = "BETTER" if md * good > 0 else "WORSE"
                regressions += verdict == "WORSE"
            print(f"{lv:7s} {arm:8s} {key:27s} {mb:12,.1f} {mn:12,.1f} {pct:+7.1f}%  "
                  f"[{lo:+11,.1f}, {hi:+11,.1f}]  {verdict}")
        bvio = sum(b[(arm, lv, s)]["interlock_violations"] for s in seeds)
        nvio = sum(n[(arm, lv, s)]["interlock_violations"] for s in seeds)
        flag = "WORSE" if nvio > bvio else ("BETTER" if nvio < bvio else "same")
        regressions += flag == "WORSE"
        print(f"{lv:7s} {arm:8s} {'interlock_violations (sum)':27s} {bvio:12d} {nvio:12d} "
              f"{'':8s}  {'':26s}  {flag}")
        print()
    print(f"significant regressions: {regressions}")
    sys.exit(1 if regressions else 0)


if __name__ == "__main__":
    main()
