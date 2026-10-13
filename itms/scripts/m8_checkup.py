"""Where does the controller still lose time? One run of CC-A-CAMP as it is (the
benchmark arm `truth`) with a per-second collector over every signal:

- halted vehicle-seconds on signal approaches, and everywhere else (unsignalised
  junctions, merges, lane changes);
- *wasted green*: seconds in which every green link of a junction has no
  vehicle on its approach lane while some red link has a halted vehicle;
- *clearance*: seconds in which a junction shows yellow or all red;
- *empty green*: seconds in which every green link is empty and no red link
  has anyone halted either (the junction idles);
- per junction, the same, so the worst junctions can be named.

Usage (from scripts/): ITMS_SCENARIO=... python m8_checkup.py <level> <seed> <out.json>
"""

from __future__ import annotations

import collections
import json
import sys

import m8_harness as M
import traci

level, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
inputs = M.ccacamp_inputs(level)
strategy = M.build_strategy("ccacamp", inputs)

state: dict = {"links": None}
per = collections.defaultdict(collections.Counter)
tot = collections.Counter()


def _init() -> None:
    links = {}
    for tl in traci.trafficlight.getIDList():
        links[tl] = [(i, ls[0][0]) for i, ls in enumerate(traci.trafficlight.getControlledLinks(tl))
                     if ls]
    state["links"] = links
    # an approach is its stop-line lane plus, where SUMO cut the road, the pieces
    # before it and the internal lanes between them (as the controller now sees it)
    chains = M.H.lane_chains()
    vias = M.H.lane_vias(M.SHORT_APPROACH_M) or {}
    up = chains[0] if chains else {}
    stop_lanes = {ln for v in links.values() for _, ln in v}
    state["road"] = {ln: [ln, *(x for x, _, _ in up.get(ln, ())), *(x for x, _ in vias.get(ln, ()))]
                     for ln in stop_lanes}
    state["signal_lanes"] = {x for v in state["road"].values() for x in v}
    state["all_lanes"] = [ln for ln in traci.lane.getIDList()]


def on_tick(step: int, t: float) -> None:
    if state["links"] is None:
        _init()
    h1 = {x: traci.lane.getLastStepHaltingNumber(x) for x in state["signal_lanes"]}
    n1 = {x: traci.lane.getLastStepVehicleNumber(x) for x in state["signal_lanes"]}
    halt = {ln: sum(h1[x] for x in xs) for ln, xs in state["road"].items()}
    num = {ln: sum(n1[x] for x in xs) for ln, xs in state["road"].items()}
    for tl, links in state["links"].items():
        s = traci.trafficlight.getRedYellowGreenState(tl)
        p = per[tl]
        p["seconds"] += 1
        h = sum(halt[ln] for ln in {ln for _, ln in links})
        p["halted_veh_s"] += h
        if "y" in s.lower() or not any(c in "Gg" for c in s):
            p["clearance_s"] += 1
            continue
        green = {ln for i, ln in links if s[i] in "Gg"}
        red_halted = any(halt[ln] > 0 for i, ln in links if s[i] in "rs" and ln not in green)
        green_empty = all(num[ln] == 0 for ln in green)
        if green_empty and red_halted:
            p["wasted_green_s"] += 1
        elif green_empty:
            p["idle_green_s"] += 1
    if int(t) % 10 == 0:
        other = 0
        for ln in state["all_lanes"]:
            if ln not in state["signal_lanes"]:
                other += traci.lane.getLastStepHaltingNumber(ln)
        tot["halted_elsewhere_veh_s"] += 10 * other


rec = M.run_scenario("ccacamp", level, seed, inputs=inputs, strategy=strategy, on_tick=on_tick,
                     tag="checkup")
for p in per.values():
    tot.update({k: v for k, v in p.items()})
stats = collections.Counter()
for s in strategy.values():
    stats.update({k: v for k, v in s.stats.items() if isinstance(v, (int, float))})
result = {
    "level": level, "seed": seed,
    "person_delay_s": rec["person_delay_s"], "entry_delay_s": rec.get("entry_delay_s"),
    "stops_per_vehicle": rec["stops_per_vehicle"], "wait": rec["wait_time_s"],
    "teleports": rec["teleports"], "totals": tot, "per_junction": per,
    "decisions": {k: v for k, v in stats.items() if k.startswith("switch") or k in
                  ("extend", "ticks", "cycles_completed")},
}
json.dump(result, open(out, "w"), indent=1, default=int)
print(json.dumps({k: result[k] for k in ("person_delay_s", "entry_delay_s", "stops_per_vehicle",
                                          "teleports")}), dict(tot))
