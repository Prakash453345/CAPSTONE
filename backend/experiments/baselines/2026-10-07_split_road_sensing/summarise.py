# ruff: noqa: E501
"""The held-out results of this baseline against TARGETS.md (run from anywhere).

Two comparisons, each per network and level: mean person-delay of both arms, the
paired change (mean of per-seed % differences, 95 % t interval), mean wait, stops,
teleports. Sensing: `truth:via2` against `truth`. Rest: `truth:via2:rest` against
`truth:via2` where that was run, against `truth` elsewhere. Then targets S1-S4, R1-R4.
"""
import json
import math
import pathlib
import statistics as st

T95 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 10: 2.262, 11: 2.228}
HERE = pathlib.Path(__file__).parent / "results"
OLD, SENSE, REST = "truth", "truth:via2", "truth:via2:rest"


def interval(xs):
    m = st.fmean(xs)
    h = T95.get(len(xs), 2.0) * st.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else float("nan")
    return m, m - h, m + h


rows = {}
for f in sorted(HERE.glob("*.json")):
    for r in json.loads(f.read_text())["records"]:
        rows.setdefault((f.stem, r["demand_level"]), {}).setdefault(r["arm"], {})[r["seed"]] = r


def table(title, new, base_of):
    print(f"\n### {title}\n")
    print("| network | level | before (s) | after (s) | change, 95 % interval | better on | mean wait before / after (s) | stops before / after | teleports before / after |")
    print("|---|---|---|---|---|---|---|---|---|")
    changes, worse, tele = {}, [], {}
    for (net, lvl), arms in sorted(rows.items()):
        base = base_of(arms)
        a, b = arms.get(new, {}), arms.get(base, {})
        seeds = sorted(set(a) & set(b))
        if len(seeds) < 2:
            continue
        rel = [(a[s]["person_delay_s"] / b[s]["person_delay_s"] - 1) * 100 for s in seeds]
        m, lo, hi = interval(rel)
        changes[(net, lvl)] = (m, lo, hi)
        t_old, t_new = (sum(x[s]["teleports"] or 0 for s in seeds) for x in (b, a))
        tele[net] = tuple(p + q for p, q in zip(tele.get(net, (0, 0)), (t_old, t_new), strict=True))
        if lo > 0:
            worse.append((net, lvl))

        def f(arm, key, seeds=seeds):
            return st.fmean(key(arm[s]) for s in seeds)

        print(f"| {net} | {lvl} | {f(b, lambda r: r['person_delay_s']):,.0f} | {f(a, lambda r: r['person_delay_s']):,.0f} | "
              f"{m:+.1f} % [{lo:+.1f}, {hi:+.1f}] | {sum(x < 0 for x in rel)}/{len(rel)} | "
              f"{f(b, lambda r: r['wait_time_s']['mean_s']):.1f} / {f(a, lambda r: r['wait_time_s']['mean_s']):.1f} | "
              f"{f(b, lambda r: r['stops_per_vehicle']):.2f} / {f(a, lambda r: r['stops_per_vehicle']):.2f} | {t_old} / {t_new} |")
    return changes, worse, tele


viol = sum(r["interlock_violations"] for arms in rows.values() for arm in (SENSE, REST)
           for r in arms.get(arm, {}).values())
ch, worse, tele = table("Sensing: `truth:via2` against `truth`", SENSE, lambda arms: OLD)
print(f"\nS1 violations in the new arms: {viol}")
for lvl in ("light", "medium"):
    if ("amaravati_plan", lvl) in ch:
        m, lo, hi = ch[("amaravati_plan", lvl)]
        print(f"S2 Amaravati plan grid {lvl}: {m:+.1f} % [{lo:+.1f}, {hi:+.1f}] -> {'pass' if m <= -10 and hi < 0 else 'FAIL'}")
print(f"S3 significantly worse on: {worse or 'none'}")
print(f"S4 teleports (before, after) by network: {tele}")

ch, worse, tele = table("Rest: `truth:via2:rest` against `truth:via2` (or `truth` where sensing changes nothing)",
                        REST, lambda arms: SENSE if SENSE in arms else OLD)
for name, lvl in (("R1", "light"), ("R2", "medium")):
    xs = [v[0] for (net, lv), v in ch.items() if lv == lvl and net != "amaravati_v2"]
    if len(xs) > 1:
        m, lo, hi = interval(xs)
        print(f"{name} {lvl}, {len(xs)} network-levels: {m:+.1f} % [{lo:+.1f}, {hi:+.1f}]; better on {sum(x < 0 for x in xs)}")
print(f"R3 significantly worse on: {worse or 'none'}")
print(f"R4 teleports (before, after) by network: {tele}; total {sum(v[0] for v in tele.values())} -> {sum(v[1] for v in tele.values())}")
