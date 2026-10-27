# ruff: noqa: E501
"""The held-out results of this baseline against TARGETS.md (run from anywhere):
`truth:rest` against `truth` per network (light demand), then targets L1-L4."""
import json
import math
import pathlib
import statistics as st

T95 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 10: 2.262}
NOT_L2 = {"amaravati_v2", "spider_lh"}  # reported only (TARGETS.md)
NOT_L4 = {"spider_lh"}  # unregulated centre junction (TARGETS.md)
HERE = pathlib.Path(__file__).parent / "results"
NEW, OLD = "truth:rest", "truth"


def interval(xs):
    m = st.fmean(xs)
    h = T95.get(len(xs), 2.0) * st.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 and st.stdev(xs) > 0 else 0.0
    return m, m - h, m + h


rows = {}
for f in sorted(HERE.glob("*.json")):
    for r in json.loads(f.read_text())["records"]:
        rows.setdefault((f.stem, r["demand_level"]), {}).setdefault(r["arm"], {})[r["seed"]] = r

print("| network | level | before (s) | after (s) | change, 95 % interval | better on | mean wait before / after (s) | stops before / after | teleports before / after |")
print("|---|---|---|---|---|---|---|---|---|")
ch, worse, more_tele, viol = {}, [], [], 0
for (net, lvl), arms in sorted(rows.items()):
    a, b = arms.get(NEW, {}), arms.get(OLD, {})
    seeds = sorted(set(a) & set(b))
    if len(seeds) < 2:
        continue
    rel = [(a[s]["person_delay_s"] / b[s]["person_delay_s"] - 1) * 100 for s in seeds]
    m, lo, hi = interval(rel)
    ch[(net, lvl)] = (m, lo, hi)
    viol += sum(a[s]["interlock_violations"] for s in seeds)
    if lo > 0:
        worse.append((net, lvl))
    dt = [(a[s]["teleports"] or 0) - (b[s]["teleports"] or 0) for s in seeds]
    if interval(dt)[1] > 0 and net not in NOT_L4:
        more_tele.append((net, lvl))

    def f(arm, key, seeds=seeds):
        return st.fmean(key(arm[s]) for s in seeds)

    print(f"| {net} | {lvl} | {f(b, lambda r: r['person_delay_s']):,.0f} | {f(a, lambda r: r['person_delay_s']):,.0f} | "
          f"{m:+.1f} % [{lo:+.1f}, {hi:+.1f}] | {sum(x < 0 for x in rel)}/{len(rel)} | "
          f"{f(b, lambda r: r['wait_time_s']['mean_s']):.1f} / {f(a, lambda r: r['wait_time_s']['mean_s']):.1f} | "
          f"{f(b, lambda r: r['stops_per_vehicle']):.2f} / {f(a, lambda r: r['stops_per_vehicle']):.2f} | "
          f"{sum(b[s]['teleports'] or 0 for s in seeds)} / {sum(a[s]['teleports'] or 0 for s in seeds)} |")

print(f"\nL1 violations in the new arm: {viol}")
lt = [v[0] for (net, lvl), v in ch.items() if lvl == "light" and net not in NOT_L2]
if len(lt) > 1:
    m, lo, hi = interval(lt)
    print(f"L2 light, {len(lt)} network-levels: {m:+.1f} % [{lo:+.1f}, {hi:+.1f}]; better on {sum(x < 0 for x in lt)}")
print(f"L3 significantly worse on: {worse or 'none'}")
print(f"L4 significantly more teleports on: {more_tele or 'none'}")
