"""Per-method tables for README.md (seeds 309-318, ITE all-red): delay per trip, p95 wait, stops, seed wins,
% difference with 95 % interval, interlock violations, teleports. Reads results/final_*.json and rl_ingolstadt_ite.json."""
import json, math, statistics as st, pathlib
from scipy.stats import t as T
H = pathlib.Path(__file__).parent / "results"
NEW = "truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3:s.ceiling_relax_hold_s=900:s.ceiling_relax_net_block=0.7:s.ceiling_relax_net_signal=max:s.ceiling_relax_net_halflife_s=60:s.ceiling_relax_net_release_s=1800:s.ceiling_relax_warmup_s=750"
L = ["light", "medium", "heavy"]
ARMS = [(NEW, "v3 (ours)"), ("truth", "paper A"), ("webster:pair", "Webster"), ("maxpressure", "max-pressure"), ("actuated", "actuated")]
SHORT = {"arterial_lh": "arterial", "berlin_adlershof": "berlin", "grid4_rh_turns": "grid4", "ingolstadt": "ingolstadt",
         "narrow_lh": "narrow", "random_lh": "random", "vijayawada_district": "vijayawada", "amaravati_v2": "amaravati"}


def iv(x):
    m = st.fmean(x); h = T.ppf(.975, len(x) - 1) * st.stdev(x) / math.sqrt(len(x)) if len(x) > 1 else 0
    return m, m - h, m + h


d = {}
for f in sorted(H.glob("final_*.json")):
    for r in json.loads(f.read_text())["records"]:
        d.setdefault((r["scenario"], r["demand_level"]), {}).setdefault(r["arm"], {})[r["seed"]] = r
cells = sorted(d, key=lambda k: (k[0], L.index(k[1])))
dpt = lambda r: r["person_delay_s"] / r["n_trips_scored"]
p95 = lambda r: r["wait_time_s"]["p95_s"]
spv = lambda r: r["stops_per_vehicle"]


def fmt_iv(x):
    m, lo, hi = iv(x)
    return "0 (identical)" if max(map(abs, x)) < 1e-9 else f"{m:+.1f} [{lo:+.1f}, {hi:+.1f}]"


out = ["## Per-network results (means over seeds 309-318)", "",
       "Delay = person-delay per scored trip (person-seconds; occupancy-weighted, buses count more). p95 = 95th-percentile wait (s). Stops = stops per vehicle.",
       "Wins = seeds where v3's person-delay is lower (ties = identical runs). % = v3 vs that method, per-seed % change in",
       "person-delay, mean and t-based 95 % interval; below 0 means v3 has less delay.", ""]
summary = []
LV = {}  # (method, level) -> lists for the per-level summary
for a, name in ARMS:
    out += [f"### {name}", ""]
    if a == NEW:
        out += ["| network | level | delay | p95 | stops | interlock viol. | teleports |", "|---|---|---|---|---|---|---|"]
    else:
        out += ["| network | level | delay | p95 | stops | v3 wins / ties | v3 vs this method (%) | interlock viol. | teleports |",
                "|---|---|---|---|---|---|---|---|---|"]
    rels, wins, ties, n_all, viol, tele, D, P, S = [], 0, 0, 0, 0, 0, [], [], []
    for k in cells:
        R = d[k][a]; seeds = sorted(R)
        dl, pp, ss = st.fmean(dpt(R[s]) for s in seeds), st.fmean(p95(R[s]) for s in seeds), st.fmean(spv(R[s]) for s in seeds)
        v = sum(R[s]["interlock_violations"] for s in seeds); tp = sum(R[s]["teleports"] or 0 for s in seeds)
        viol += v; tele += tp; D.append(dl); P.append(pp); S.append(ss)
        z = LV.setdefault((name, k[1]), dict(D=[], P=[], S=[], x=[], w=0, t=0, n=0, v=0, tp=0))
        z["D"].append(dl); z["P"].append(pp); z["S"].append(ss); z["v"] += v; z["tp"] += tp
        row = f"| {SHORT[k[0]]} | {k[1]} | {dl:.1f} | {pp:.1f} | {ss:.2f} |"
        if a != NEW:
            n = d[k][NEW]; c = sorted(set(n) & set(R))
            x = [(n[s]["person_delay_s"] / R[s]["person_delay_s"] - 1) * 100 for s in c]
            w = sum(v_ < -1e-9 for v_ in x); t_ = sum(abs(v_) < 1e-9 for v_ in x)
            wins += w; ties += t_; n_all += len(c); rels.append(st.fmean(x))
            z["x"].append(st.fmean(x)); z["w"] += w; z["t"] += t_; z["n"] += len(c)
            row += f" {w}/{len(c)}" + (f" ({t_} ties)" if t_ else "") + f" | {fmt_iv(x)} |"
        out.append(row + f" {v} | {tp} |")
    out.append("")
    summary.append((name, st.fmean(D), st.fmean(P), st.fmean(S), wins, ties, n_all, iv(rels) if rels else None, viol, tele))

top = ["## Summary across all 24 network-levels (240 runs per method)", "",
       "| method | mean person-delay per trip (s) | mean p95 wait (s) | stops per vehicle | v3 wins / ties (of 240 seeds) | v3 vs method, pooled % [95 % interval] | interlock violations | teleports |",
       "|---|---|---|---|---|---|---|---|"]
for name, dl, pp, ss, w, t_, n, p, v, tp in summary:
    top.append(f"| {name} | {dl:.1f} | {pp:.1f} | {ss:.2f} | " + ("-" if p is None else f"{w} / {t_}") + " | "
               + ("-" if p is None else f"{p[0]:+.1f} [{p[1]:+.1f}, {p[2]:+.1f}]") + f" | {v} | {tp} |")
top += ["", "Delay, p95 and stops here are means of the 24 per-cell means, so the heavy gridlocking cells (thousands of seconds",
        "per trip) dominate them; the pooled % (t interval across the 24 per-cell mean % changes, each cell weighted equally)",
        "is the headline comparison. The same by demand level (8 networks each):", "",
        "| level | method | mean person-delay per trip (s) | mean p95 wait (s) | stops per vehicle | v3 wins / ties (of 80) | v3 vs method, pooled % [95 % interval] | interlock violations | teleports |",
        "|---|---|---|---|---|---|---|---|---|"]
for l in L:
    for _, name in ARMS:
        z = LV[(name, l)]; pm = iv(z["x"]) if z["x"] else None
        top.append(f"| {l} | {name} | {st.fmean(z['D']):.1f} | {st.fmean(z['P']):.1f} | {st.fmean(z['S']):.2f} | "
                   + ("-" if pm is None else f"{z['w']} / {z['t']}") + " | "
                   + ("-" if pm is None else ("0 (identical)" if max(map(abs, z['x'])) < 1e-9 else f"{pm[0]:+.1f} [{pm[1]:+.1f}, {pm[2]:+.1f}]"))
                   + f" | {z['v']} | {z['tp']} |")
top += [""]

rl = H / "rl_ingolstadt_ite.json"
if rl.exists():
    Rl = {}
    for r in json.loads(rl.read_text())["records"]:
        Rl.setdefault(r["demand_level"], {})[r["seed"]] = r
    top += ["## PressLight (RL, paper A's trained models), ingolstadt only", "",
            "| level | method | delay | p95 | stops | v3 wins | v3 vs PressLight (%) | interlock viol. | teleports | unfinished trips |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for l in L:
        n = d[("ingolstadt", l)][NEW]; p = Rl[l]; c = sorted(set(n) & set(p))
        x = [(n[s]["person_delay_s"] / p[s]["person_delay_s"] - 1) * 100 for s in c]
        for lab, R in (("PressLight", p), ("v3 (ours)", n)):
            top.append(f"| {l} | {lab} | {st.fmean(dpt(R[s]) for s in c):.1f} | {st.fmean(p95(R[s]) for s in c):.1f} | "
                       f"{st.fmean(spv(R[s]) for s in c):.2f} | " + (f"{sum(v_ < 0 for v_ in x)}/{len(c)} | {fmt_iv(x)}" if lab == "PressLight" else "- | -")
                       + f" | {sum(R[s]['interlock_violations'] for s in c)} | {sum(R[s]['teleports'] or 0 for s in c)} | {sum(R[s].get('unfinished_at_cap') or 0 for s in c)} |")
    top += ["", "At medium and heavy PressLight leaves many trips unfinished at the time cap; delay is measured on finished trips,",
            "so its delay there is not comparable (it looks low because the stuck vehicles are not scored).", ""]
print("\n".join(top + out))
