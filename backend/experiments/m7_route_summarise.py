"""Paired comparison of EV travel time between arms (bootstrap 95 % CI).

usage: m7_route_summarise.py results/*.jsonl [--pairs eta_rr:weighted,...]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict


def boot_ci(xs, n=4000, seed=0):
    r = random.Random(seed)
    ms = sorted(statistics.fmean(r.choices(xs, k=len(xs))) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--pairs", default="eta_rr:weighted,eta_rr:dist,eta:weighted,eta_rr:eta,"
                    "eta_hex:eta_rr")
    a = ap.parse_args()
    rows = [json.loads(line) for f in a.files for line in open(f) if line.strip()]
    by = defaultdict(dict)  # (net, level, incident, seed) -> arm -> row
    for r in rows:
        by[(r["net"], r["level"], r["incident"], r["seed"])][r["arm"]] = r
    groups = defaultdict(list)
    for k, arms in by.items():
        groups[(k[0], k[1], k[2])].append(arms)
        groups[("ALL", "", k[2])].append(arms)
    print("| net | level | incident | arm | n | mean EV s | DNF | reroutes/run |")
    print("|---|---|---|---|---|---|---|---|")
    for g, lst in sorted(groups.items()):
        for arm in ("dist", "weighted", "eta", "eta_rr", "eta_hex"):
            xs = [x[arm] for x in lst if arm in x]
            if not xs:
                continue
            print(f"| {g[0]} | {g[1]} | {int(g[2])} | {arm} | {len(xs)} | "
                  f"{statistics.fmean(r['ev_time_s'] for r in xs):.1f} | "
                  f"{sum(not r['arrived'] for r in xs)} | "
                  f"{statistics.fmean(r['reroutes'] for r in xs):.2f} |")
    print()
    print("| net | level | incident | A vs B | n | mean diff s [95% CI] | mean % [95% CI] |")
    print("|---|---|---|---|---|---|---|")
    for g, lst in sorted(groups.items()):
        for pair in a.pairs.split(","):
            x, y = pair.split(":")
            d = [(s[x]["ev_time_s"], s[y]["ev_time_s"]) for s in lst if x in s and y in s]
            if len(d) < 3:
                continue
            diff = [p - q for p, q in d]
            pct = [100 * (p - q) / q for p, q in d]
            lo, hi = boot_ci(diff)
            plo, phi = boot_ci(pct)
            print(f"| {g[0]} | {g[1]} | {int(g[2])} | {x} vs {y} | {len(d)} | "
                  f"{statistics.fmean(diff):+.1f} [{lo:+.1f}, {hi:+.1f}] | "
                  f"{statistics.fmean(pct):+.1f} [{plo:+.1f}, {phi:+.1f}] |")
    hexrows = [r for r in rows if r["arm"] == "eta_hex"]
    full = [r for r in rows if r["arm"] == "eta_rr"]
    if hexrows and full:
        print()
        for name, rs in (("eta_rr", full), ("eta_hex", hexrows)):
            print(f"{name}: plan ms mean {statistics.fmean(r['plan_ms_mean'] for r in rs):.1f}, "
                  f"max {max(r['plan_ms_max'] for r in rs):.1f}; edges sampled/tick "
                  f"{statistics.fmean(r['edges_sampled_per_tick'] for r in rs):.0f}")


if __name__ == "__main__":
    main()
