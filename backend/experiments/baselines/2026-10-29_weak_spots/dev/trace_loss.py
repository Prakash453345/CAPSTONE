"""Where green time is lost, for ANY arm (ours, actuated, max-pressure...). Per second, per signal:
 clear      - showing yellow / all-red
 wasted     - green, every green link's approach lane empty, while some red link has a halted vehicle
 blocked    - green, some green link has halted vehicles but its exit lane is jammed (>=70 % occupied,
              halting): the green cannot discharge (spillback)
 useful     - the rest of green time
Usage (from itms/): trace_loss.py <arm> <level> <seed> <out.json>"""
import sys, json, collections
sys.path.insert(0, "scripts")
import traci
orig = traci.simulationStep
st = {"links": None}
tot = collections.Counter(); per = collections.defaultdict(collections.Counter)
def init():
    st["links"] = {tl: [(i, ls[0][0], ls[0][1]) for i, ls in enumerate(traci.trafficlight.getControlledLinks(tl)) if ls]
                   for tl in traci.trafficlight.getIDList()}
def step(*a, **k):
    orig(*a, **k)
    if st["links"] is None: init()
    cache = {}
    def lane(l):
        if l not in cache:
            cache[l] = (traci.lane.getLastStepVehicleNumber(l), traci.lane.getLastStepHaltingNumber(l),
                        traci.lane.getLastStepOccupancy(l))
        return cache[l]
    for tl, links in st["links"].items():
        s = traci.trafficlight.getRedYellowGreenState(tl)
        if "y" in s.lower() or not any(c in "Gg" for c in s):
            k2 = "clear"
        else:
            green = [(i, a_, b_) for i, a_, b_ in links if s[i] in "Gg"]
            red = [(i, a_, b_) for i, a_, b_ in links if s[i] in "rR"]
            if all(lane(a_)[0] == 0 for _, a_, _ in green):
                k2 = "wasted" if any(lane(a_)[1] > 0 for _, a_, _ in red) else "idle"
            elif any(lane(a_)[1] > 0 and lane(b_)[2] >= 0.7 and lane(b_)[1] > 0 for _, a_, b_ in green):
                k2 = "blocked"
            else:
                k2 = "useful"
        tot[k2] += 1; per[tl][k2] += 1
traci.simulationStep = step
import m8_closed_loop_gate as G
arm, level, seed, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
rec = G._job((arm, level, seed, 5.0))
n = sum(tot.values())
res = {"arm": arm, "delay": rec["person_delay_s"], "teleports": rec["teleports"],
       "share": {k: round(v / n, 3) for k, v in tot.items()}, "per": {t: dict(c) for t, c in per.items()}}
json.dump(res, open(out, "w"), indent=1)
print(arm, level, seed, round(rec["person_delay_s"]), "tele", rec["teleports"], res["share"])
