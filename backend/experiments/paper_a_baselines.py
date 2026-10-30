"""Paper-A baselines added 2026-10-28: plain max-pressure and SUMO's built-in
actuated control, run on exactly the same networks, demand, seeds, phases and
clearance times as CC-A-CAMP and Webster.

- `maxpressure`: `sim_service.control.strategies.maxpressure.MaxPressure`
  inside the project's own runner (same sensing, same safety kernel).
- `actuated[:<maxdur>]`: SUMO's own `type="actuated"` traffic light (gap-based
  extension with SUMO-placed induction loops, max-gap 3.0 s), one program per
  junction built from the same Tier0Config phases the other controllers use
  (paired layout included) and the same yellow and all-red (flat 2.0 s or ITE,
  whatever SIGNAL_ALL_RED selects). minDur = the junction's minimum green,
  maxDur = <maxdur> s (default 50 s, netconvert's default for actuated).
  The project's interlock kernel cannot sit in front of SUMO's own program, so
  the run is checked from outside every step instead: two protected ('G')
  conflicting movements shown together count as an interlock violation.
"""

from __future__ import annotations

import time
from pathlib import Path
from xml.sax.saxutils import quoteattr

import m5_harness as H
import m8_harness as M
from sim_service.control import metrics
from sim_service.control.runner import _ensure_sumo_home, _resolve_sumo_binary
from sim_service.control.strategies.maxpressure import MaxPressure
from sim_service.signal_controller.traci_cabinet import TraCICabinet

ACTUATED_MAX_DUR_S = 50.0
MAX_GAP_S = 3.0


def baseline_inputs(level: str):
    """Webster's signal program on the adopted phase layout (paired phases on
    split-phased junctions): the program every baseline runs on."""
    return M._scenario_inputs(level, layout=M.PHASE_LAYOUT)  # noqa: SLF001


def run_maxpressure(level: str, seed: int, slot_s: float = 10.0, tag: str = "maxpressure"):
    inputs = baseline_inputs(level)
    strategy = {tls: MaxPressure(slot_s=slot_s) for tls in inputs[0]}
    return M.run_scenario("maxpressure", level, seed, inputs=inputs, strategy=strategy, tag=tag)


def _actuated_xml(configs, state_len: dict[str, int], max_dur: float) -> str:
    out = ["<additional>"]
    for tls, cfg in configs.items():
        cab = TraCICabinet(tls, cfg.phases, state_len[tls])
        out.append(f'  <tlLogic id={quoteattr(tls)} type="actuated" programID="act" offset="0">')
        out.append(f'    <param key="max-gap" value="{MAX_GAP_S}"/>')
        for pid in cfg.ring_order:
            g = cab._state_by_phase[pid]  # noqa: SLF001
            mn = cfg.min_green_s.get(pid, 5.0)
            out.append(f'    <phase duration="{mn}" minDur="{mn}" maxDur="{max(mn, max_dur)}" '
                       f'state="{g}"/>')
            y = "".join("y" if c in "Gg" else "r" for c in g)
            out.append(f'    <phase duration="{cfg.yellow_s}" state="{y}"/>')
            if cfg.all_red_s > 0:
                out.append(f'    <phase duration="{cfg.all_red_s}" state="{"r" * len(g)}"/>')
        out.append("  </tlLogic>")
    out.append("</additional>")
    return "\n".join(out)


def run_actuated(level: str, seed: int, max_dur: float = ACTUATED_MAX_DUR_S,
                 tag: str = "actuated", tripinfo_dir: Path = Path("/tmp/m8_tripinfo")) -> dict:
    import traci  # noqa: PLC0415

    configs, flows, pcu, paths = baseline_inputs(level)
    _ensure_sumo_home()
    tripinfo_dir.mkdir(parents=True, exist_ok=True)
    stem = f"act_{H.SCENARIO_NAME}_{level}_s{seed}_{time.time_ns()}"
    trip = tripinfo_dir / f"{stem}.xml"
    add = tripinfo_dir / f"{stem}.add.xml"
    # state lengths come from the network's own programs
    import sumolib  # noqa: PLC0415

    net = sumolib.net.readNet(str(H.NET_PATH), withPrograms=True)
    state_len = {}
    for tls in configs:
        progs = net.getTLS(tls).getPrograms()
        state_len[tls] = len(next(iter(progs.values())).getPhases()[0].state)
    add.write_text(_actuated_xml(configs, state_len, max_dur))
    args = [_resolve_sumo_binary(), "-c", str(paths["sumocfg"]), "--step-length", "1.0",
            "--no-step-log", "true", "--time-to-teleport", "300", "--seed", str(seed),
            "--tripinfo-output", str(trip), "--additional-files", str(add)]
    t0 = time.time()
    traci.start(args)
    try:
        for tls in configs:
            traci.trafficlight.setProgram(tls, "act")
        conflicts = {tls: [(int(a[1:]), int(b[1:])) for a, bs in cfg.conflict_matrix.items()
                           for b in bs if a < b] for tls, cfg in configs.items()}
        viol, teleports, step, unfinished = 0, 0, 0, 0
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            step += 1
            teleports += traci.simulation.getStartingTeleportNumber()
            for tls, pairs in conflicts.items():
                s = traci.trafficlight.getRedYellowGreenState(tls)
                if any(s[i] == "G" and s[j] == "G" for i, j in pairs):
                    viol += 1
            if step >= H.MAX_STEPS_SAFETY_CAP:
                unfinished = traci.simulation.getMinExpectedNumber()
                break
    finally:
        traci.close()
    m = metrics.compute_run_metrics(trip, paths["route"])
    rec = {
        "scenario": H.SCENARIO_NAME, "controller": "actuated", "demand_level": level,
        "seed": seed, "steps": step, "interlock_violations": viol, "teleports": teleports,
        "unfinished_at_cap": unfinished, "person_delay_s": m.person_delay_s,
        "n_trips_total": m.n_trips_total, "n_trips_scored": m.n_trips_scored,
        "entry_delay_s": m.entry_delay_person_s,
        "person_throughput_per_hour": m.person_throughput_per_hour,
        "stops_per_vehicle": m.stops_per_vehicle,
        "wait_time_s": {"mean_s": m.wait_time_s.mean_s, "p95_s": m.wait_time_s.p95_s,
                        "max_s": m.wait_time_s.max_s},
        "wall_s": round(time.time() - t0, 1), "actuated_max_dur_s": max_dur,
    }
    trip.unlink(missing_ok=True)
    add.unlink(missing_ok=True)
    return rec
