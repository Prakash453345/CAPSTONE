# ruff: noqa: E501
"""Markdown tables of the held-out results in results/ (run from anywhere).

Per network and demand level: mean person-delay of every arm, its teleports, the runs
without one, interlock violations, junction-ticks with a call waiting past the
configured maximum wait (and the worst excess), and the paired difference in
person-delay against a base arm (mean of per-seed % differences, 95 % t interval).
"""
import collections
import json
import math
import pathlib
import statistics as st
import sys

T95 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262}
HERE = pathlib.Path(__file__).parent / (sys.argv[1] if len(sys.argv) > 1 else "results")
ORDER = ["narrow_lh", "narrow_sweep", "narrow_sweep_parts", "corridor", "berlin_adlershof",
         "vijayawada_district", "narrow_sweep_cameras", "narrow_lh_cameras"]


def paired(a, b):
    seeds = sorted(set(a) & set(b))
    if len(seeds) < 2:
        return ""
    rel = [(a[s]["person_delay_s"] - b[s]["person_delay_s"]) / b[s]["person_delay_s"] * 100 for s in seeds]
    m = st.fmean(rel)
    h = T95[len(rel)] * st.stdev(rel) / math.sqrt(len(rel))
    return f"{m:+.1f} % [{m - h:+.1f}, {m + h:+.1f}], better on {sum(x < 0 for x in rel)}/{len(rel)}"


for name in ORDER:
    f = HERE / f"{name}.json"
    if not f.exists():
        continue
    rows = collections.defaultdict(dict)
    for r in json.loads(f.read_text())["records"]:
        rows[(r["demand_level"], r["arm"])][r["seed"]] = r
    print(f"\n### {name}\n")
    print("| level | arm | runs | mean person-delay (s) | vs CC-A-CAMP | vs Webster | teleports | runs without one | interlock violations | ticks past max wait (worst excess s) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for (lvl, arm), by in sorted(rows.items()):
        rs = list(by.values())
        over = sum(r.get("waits_over_bound") or 0 for r in rs)
        worst = max((r.get("longest_wait_excess_s") or -math.inf) for r in rs)
        print(f"| {lvl} | {arm} | {len(rs)} | {st.fmean(r['person_delay_s'] for r in rs):,.0f} | "
              f"{'' if arm == 'truth' else paired(by, rows.get((lvl, 'truth'), {}))} | "
              f"{'' if arm == 'webster' else paired(by, rows.get((lvl, 'webster'), {}))} | "
              f"{sum(r.get('teleports') or 0 for r in rs)} | {sum(not r.get('teleports') for r in rs)} | "
              f"{sum(r['interlock_violations'] for r in rs)} | {over}{f' ({worst:+.1f})' if over else ''} |")

same = []
for f in sorted(HERE.glob("identical_*.json")):
    d = {r["arm"]: r for r in json.loads(f.read_text())["records"]}
    same.append(f"{f.stem[10:]} {'identical' if d['truth']['person_delay_s'] == d['hol']['person_delay_s'] else 'DIFFERENT'}")
if same:
    print("\n### networks with no variant (heavy, seed 1): " + "; ".join(same))
