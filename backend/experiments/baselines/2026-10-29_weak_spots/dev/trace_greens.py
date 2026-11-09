"""Record every signal state change per junction during one run of any arm, then summarise
green lengths, change-interval share and cycle length. Usage: trace_greens.py <arm> <level> <seed> <out.json>"""
import sys, json, collections
sys.path.insert(0, "scripts")
import traci
orig = traci.simulationStep
log = collections.defaultdict(list)   # tls -> [(t, state)]
def step(*a, **k):
    orig(*a, **k)
    t = traci.simulation.getTime()
    for tls in traci.trafficlight.getIDList():
        s = traci.trafficlight.getRedYellowGreenState(tls)
        if not log[tls] or log[tls][-1][1] != s:
            log[tls].append((t, s))
traci.simulationStep = step
import m8_closed_loop_gate as G
arm, level, seed, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
rec = G._job((arm, level, seed, 5.0))
summ = {}
for tls, ev in log.items():
    greens, clear, total = [], 0.0, ev[-1][0] - ev[0][0]
    for (t0, s), (t1, _) in zip(ev, ev[1:]):
        d = t1 - t0
        if "y" in s.lower() or not any(c in "Gg" for c in s): clear += d
        else: greens.append(d)
    summ[tls] = {"n_greens": len(greens), "mean_green": sum(greens)/max(1,len(greens)),
                 "clear_share": clear/max(1,total), "greens": greens[:400]}
json.dump({"rec": {k: rec[k] for k in ("person_delay_s","teleports","stops_per_vehicle")}, "tls": summ,
           "events": {t: e[:3000] for t, e in log.items()}}, open(out, "w"))
print(arm, rec["person_delay_s"], {t: (v["n_greens"], round(v["mean_green"],1), round(v["clear_share"],2)) for t, v in list(summ.items())[:6]})
