# ruff: noqa: E501
"""The held-out results of this baseline against TARGETS.md (run from anywhere).

Per network and level: mean person-delay of both arms, the paired change (mean of
per-seed % differences, 95 % t interval), mean wait, stops, the wait to enter the
network as a share of person-delay, teleports, violations. Then targets F1-F5.
"""
import json
import math
import pathlib
import statistics as st

T95 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 10: 2.262, 19: 2.101, 22: 2.080}
HERE = pathlib.Path(__file__).parent / "results"
NEW, OLD = "truth:f20", "truth"


def interval(xs):
    m = st.fmean(xs)
    h = T95.get(len(xs), 2.0) * st.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else float("nan")
    return m, m - h, m + h


rows = {}
for f in sorted(HERE.glob("*.json")):
    for r in json.loads(f.read_text())["records"]:
        rows.setdefault((f.stem, r["demand_level"]), {}).setdefault(r["arm"], {})[r["seed"]] = r

print("| network | level | CC-A-CAMP (s) | with floor (s) | change, 95 % interval | better on | mean wait old / new (s) | stops old / new | entry wait, % of delay | teleports old / new |")
print("|---|---|---|---|---|---|---|---|---|---|")
changes, worse, violations = {}, [], 0
for (net, lvl), arms in sorted(rows.items()):
    a, b = arms.get(NEW, {}), arms.get(OLD, {})
    seeds = sorted(set(a) & set(b))
    if len(seeds) < 2:
        continue
    rel = [(a[s]["person_delay_s"] / b[s]["person_delay_s"] - 1) * 100 for s in seeds]
    m, lo, hi = interval(rel)
    changes[(net, lvl)] = (m, lo, hi)
    violations += sum(a[s]["interlock_violations"] for s in seeds)
    if lo > 0:
        worse.append((net, lvl))
    def f(arm, key, seeds=seeds):
        return st.fmean(key(arm[s]) for s in seeds)

    entry = f(a, lambda r: (r.get("entry_delay_s") or 0)) / f(a, lambda r: r["person_delay_s"]) * 100
    print(f"| {net} | {lvl} | {f(b, lambda r: r['person_delay_s']):,.0f} | {f(a, lambda r: r['person_delay_s']):,.0f} | "
          f"{m:+.1f} % [{lo:+.1f}, {hi:+.1f}] | {sum(x < 0 for x in rel)}/{len(rel)} | "
          f"{f(b, lambda r: r['wait_time_s']['mean_s']):.1f} / {f(a, lambda r: r['wait_time_s']['mean_s']):.1f} | "
          f"{f(b, lambda r: r['stops_per_vehicle']):.2f} / {f(a, lambda r: r['stops_per_vehicle']):.2f} | {entry:.1f} | "
          f"{sum(b[s]['teleports'] or 0 for s in seeds)} / {sum(a[s]['teleports'] or 0 for s in seeds)} |")

lm = [v[0] for (_, lvl), v in changes.items() if lvl in ("light", "medium")]
hv = [v[0] for (_, lvl), v in changes.items() if lvl == "heavy"]
print(f"\nF1 violations in the new arm: {violations}")
if len(lm) > 1:
    m, lo, hi = interval(lm)
    print(f"F2 light and medium, {len(lm)} network-levels: {m:+.1f} % [{lo:+.1f}, {hi:+.1f}]; better on {sum(x < 0 for x in lm)}")
for lvl in ("light", "medium"):
    if ("amaravati_plan", lvl) in changes:
        print(f"F3 Amaravati plan grid {lvl}: {changes[('amaravati_plan', lvl)][0]:+.1f} % [{changes[('amaravati_plan', lvl)][1]:+.1f}, {changes[('amaravati_plan', lvl)][2]:+.1f}]")
print(f"F4 significantly worse on: {worse or 'none'}")
if hv:
    print(f"F5 heavy, {len(hv)} network-levels: mean {st.fmean(hv):+.1f} % {[round(x, 1) for x in hv]}")
