"""Target verdicts (TARGETS.md) from results/. Run after summarise.py."""
from scipy.stats import t as _t
import json, glob, math, statistics as st, pathlib
H = pathlib.Path(__file__).parent / "results"
T = {5: 2.776, 10: 2.262}
def iv(x):
    m = st.fmean(x); s = st.stdev(x) if len(x) > 1 else 0
    h = _t.ppf(0.975, len(x) - 1) * s / math.sqrt(len(x)); return m, m - h, m + h
L = ["light", "medium", "heavy"]
def load(p):
    d = {}
    for f in sorted(H.glob(p)):
        net = f.name.split("_", 1)[1].rsplit("_", 1)[0]
        for r in json.loads(f.read_text())["records"]:
            d.setdefault((net, r["demand_level"]), {}).setdefault(r["arm"], {})[r["seed"]] = r
    return d
ite, flat = load("main_*_ite.json"), load("main_*_flat.json")
cells = sorted(ite, key=lambda k: (k[0], L.index(k[1])))
def cmp(a, b, key=lambda r: r["person_delay_s"]):
    c = sorted(set(a) & set(b)); rel = [(key(a[s]) / key(b[s]) - 1) * 100 for s in c]
    return iv(rel) + (sum(x < 0 for x in rel), len(c))
print("| network | level | vs Webster | vs Max-pressure | vs Actuated | p95 vs Webster | teleports ours/W/MP/A |")
print("|---|---|---|---|---|---|---|")
res = {a: [] for a in ["webster:pair", "maxpressure", "actuated"]}; p95w = []; tele_worse = []
for k in cells:
    d = ite[k]; o = d["truth"]; row = []
    for a in res:
        m, lo, hi, w, n = cmp(o, d[a]); res[a].append((k, m, lo, hi)); row.append(f"{m:+.1f} [{lo:+.1f}, {hi:+.1f}] {w}/{n}")
    m, lo, hi, w, n = cmp(o, d["webster:pair"], key=lambda r: max(r["wait_time_s"]["p95_s"], 1)); p95w.append((k, lo > 0))
    row.append(f"{m:+.1f} [{lo:+.1f}, {hi:+.1f}]")
    dt = [(o[s]["teleports"] or 0) - (d["webster:pair"][s]["teleports"] or 0) for s in o]
    if iv(dt)[1] > 0: tele_worse.append(k)
    tp = "/".join(str(sum(d[a][s]["teleports"] or 0 for s in d[a])) for a in ["truth", "webster:pair", "maxpressure", "actuated"])
    print(f"| {k[0]} | {k[1]} | " + " | ".join(row) + f" | {tp} |")
viol = sum(r["interlock_violations"] for D in (ite, flat) for d in D.values() for r in d["truth"].values())
print("\nS1 ours interlock violations (ITE+flat):", viol, "->", "PASS" if viol == 0 else "FAIL")
print("S2 cells where ours teleports significantly more than Webster:", tele_worse or "none", "->", "PASS" if not tele_worse else "FAIL")
for a, need_b, max_w, tag in [("webster:pair", 18, 2, "W1/W2"), ("maxpressure", 16, 3, "M1"), ("actuated", 16, 3, "A1")]:
    b = [k for k, m, lo, hi in res[a] if hi < 0]; w = [k for k, m, lo, hi in res[a] if lo > 0]
    print(f"{tag} vs {a}: significantly better {len(b)}/24 (need >= {need_b}), worse {len(w)}/24 (allow <= {max_w}) -> "
          f"{'PASS' if len(b) >= need_b and len(w) <= max_w else 'FAIL'}; worse on: {w}")
pi = iv([m for k, m, lo, hi in res['webster:pair']])
pf = iv([cmp(flat[k]["truth"], flat[k]["webster:pair"])[0] for k in cells])
print(f"W3 pooled vs Webster: ITE {pi[0]:+.1f} [{pi[1]:+.1f}, {pi[2]:+.1f}], flat {pf[0]:+.1f} [{pf[1]:+.1f}, {pf[2]:+.1f}], gap {abs(pi[0]-pf[0]):.1f} pts -> {'PASS' if abs(pi[0]-pf[0]) <= 5 else 'FAIL'}")
pw = [k for k, worse in p95w if worse]
print(f"P1 ours p95 wait significantly higher than Webster on {len(pw)}/24 (allow <= 3) -> {'PASS' if len(pw) <= 3 else 'FAIL'}: {pw}")
rl = load("rl_*_ite.json")
if rl:
    for k in sorted(rl, key=lambda k: L.index(k[1])):
        p = rl[k].get("rl") or next(iter(rl[k].values()))
        m, lo, hi, w, n = cmp(ite[k]["truth"], p)
        tp = sum(r["teleports"] for r in p.values()); to = sum(ite[k]["truth"][s]["teleports"] or 0 for s in p)
        print(f"R1 ingolstadt {k[1]}: ours vs PressLight {m:+.1f} [{lo:+.1f}, {hi:+.1f}] {w}/{n}; teleports ours {to}, RL {tp}")
