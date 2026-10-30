"""Weak-spots final test: tables and TARGETS.md verdicts (N1-N7) from results/final_*_ite.json (+ preethi files)."""
import json, glob, math, statistics as st, pathlib
from scipy.stats import t as T
H = pathlib.Path(__file__).parent / "results"
NEW = "truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3"
L = ["light", "medium", "heavy"]
def iv(x):
    m = st.fmean(x); h = T.ppf(.975, len(x)-1) * st.stdev(x) / math.sqrt(len(x)) if len(x) > 1 else 0
    return m, m-h, m+h
d = {}
for f in sorted(H.glob("final_*.json")):
    for r in json.loads(f.read_text())["records"]:
        d.setdefault((r["scenario"], r["demand_level"]), {}).setdefault(r["arm"], {})[r["seed"]] = r
cells = sorted(d, key=lambda k: (k[0], L.index(k[1])))
names = {"truth": "paper A", "webster:pair": "Webster", "maxpressure": "max-pressure", "actuated": "actuated"}
res = {a: [] for a in names}; tele_worse = []; p95_worse = []; viol = 0
print("| network | level | new vs paper A | vs Webster | vs max-pressure | vs actuated | teleports new / A / W / MP / act |")
print("|---|---|---|---|---|---|---|")
for k in cells:
    n = d[k][NEW]; row = []; viol += sum(r["interlock_violations"] for r in n.values())
    for a in names:
        b = d[k][a]; c = sorted(set(n) & set(b))
        rel = [(n[s]["person_delay_s"]/b[s]["person_delay_s"]-1)*100 for s in c]
        m, lo, hi = iv(rel); res[a].append((k, m, lo, hi)); row.append(f"{m:+.1f} [{lo:+.1f}, {hi:+.1f}] {sum(x<0 for x in rel)}/{len(c)}")
    o = d[k]["truth"]; c = sorted(set(n) & set(o))
    if len(c) > 1 and iv([(n[s]["teleports"] or 0)-(o[s]["teleports"] or 0) for s in c])[1] > 0: tele_worse.append(k)
    if len(c) > 1 and iv([n[s]["wait_time_s"]["p95_s"]-o[s]["wait_time_s"]["p95_s"] for s in c])[1] > 0: p95_worse.append(k)
    tp = " / ".join(str(sum(d[k][a][s]["teleports"] or 0 for s in d[k][a])) for a in [NEW, "truth", "webster:pair", "maxpressure", "actuated"])
    print(f"| {k[0]} | {k[1]} | " + " | ".join(row) + f" | {tp} |")
N = len(cells)
print(f"\ncells: {N} of 24")
print("N1 interlock violations (new):", viol, "->", "PASS" if viol == 0 else "FAIL")
pm = iv([m for _, m, _, _ in res["truth"]]); b = sum(hi < 0 for *_, hi in res["truth"]); w = sum(lo > 0 for _, _, lo, _ in res["truth"])
print(f"N2 vs paper A: pooled {pm[0]:+.1f} [{pm[1]:+.1f}, {pm[2]:+.1f}], better {b}, worse {w} -> {'PASS' if pm[2] < 0 and b >= 8 and w <= 2 else 'FAIL'}; worse on {[k for k, m, lo, hi in res['truth'] if lo > 0]}")
print("N3 teleports significantly more than paper A on:", tele_worse or "none", "->", "PASS" if not tele_worse else "FAIL")
for a, nb, nw, tag in [("webster:pair", 19, 1, "N4"), ("maxpressure", 16, 3, "N5"), ("actuated", 16, 3, "N6")]:
    b = [k for k, m, lo, hi in res[a] if hi < 0]; w = [k for k, m, lo, hi in res[a] if lo > 0]
    print(f"{tag} vs {names[a]}: better {len(b)}/{N} (need >= {nb}), worse {len(w)}/{N} (allow <= {nw}) -> {'PASS' if len(b) >= nb and len(w) <= nw else 'FAIL'}; worse on {w}")
print(f"N7 p95 wait significantly higher than paper A on {len(p95_worse)}/{N} (allow <= 2) -> {'PASS' if len(p95_worse) <= 2 else 'FAIL'}: {p95_worse}")
for a in names:
    p = iv([m for _, m, _, _ in res[a]]); print(f"pooled new vs {names[a]}: {p[0]:+.1f} [{p[1]:+.1f}, {p[2]:+.1f}]")
rl = H / "rl_ingolstadt_ite.json"
if rl.exists():
    R = {}
    for r in json.loads(rl.read_text())["records"]: R.setdefault(r["demand_level"], {})[r["seed"]] = r
    for l in L:
        n = d[("ingolstadt", l)][NEW]; p = R[l]; c = sorted(set(n) & set(p))
        m, lo, hi = iv([(n[s]["person_delay_s"]/p[s]["person_delay_s"]-1)*100 for s in c])
        print(f"RL ingolstadt {l}: new vs PressLight {m:+.1f} [{lo:+.1f}, {hi:+.1f}]; teleports new {sum(n[s]['teleports'] or 0 for s in c)}, RL {sum(p[s]['teleports'] for s in c)}; unfinished RL {sum(p[s]['unfinished_at_cap'] for s in c)}")
