"""Real-SUMO exercise of `IncidentInjector` -- the pytest suite only drives
it against a monkeypatched TraCI, so this is where it meets an actual SUMO
process. Not part of the test suite, same as the other `smoke_*` scripts.

Two checks, both printed as a pass/fail line:

  1. standalone_probe -- drives a bare TraCI loop with the injector attached
     and watches the target lane every tick. Proves a stall actually drops a
     real vehicle to 0 m/s for the scheduled window and it recovers after,
     and that a lane-block actually drops and then restores the lane's max
     speed. This is the "the intervention does what it says" check.

  2. through_runner -- runs the full `run_controlled_scenario` with the same
     injector, i.e. with the arbitration ladder governing every junction at
     the same time. Proves the injector coexists with real control and that
     `finalize` leaves nothing throttled or frozen behind (no interlock
     violations attributable to a stuck lane, every window closed with a
     `released` / `run_ended` reason, none stuck open).

Usage:  python scripts/smoke_m6_injector.py [demand_suffix]
        (demand_suffix e.g. `_light` (default) / `` (medium) / `_heavy`)
"""

from __future__ import annotations

import sys
from pathlib import Path

import traci
from sim_service.control.anomaly.injector import IncidentInjector, random_schedule
from sim_service.control.runner import (
    _ensure_sumo_home,
    _resolve_sumo_binary,
    run_controlled_scenario,
)

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "data" / "scenarios" / "networks" / "vijayawada"))
from extract_tier0_config import load_configs  # noqa: E402
from link_lanes import link_to_lane_map  # noqa: E402

_NET = _ROOT / "data" / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
_DEMAND = _ROOT / "data" / "scenarios" / "demand" / "vijayawada"

_SEED = 42
_INCIDENT_SEED = 7
_RUN_TICKS = 2400  # a short run -- enough to hold a couple of full incidents
_N_INCIDENTS = 3


def _controlled_lanes() -> list[str]:
    link_lanes = link_to_lane_map(_NET)
    return sorted({lane for links in link_lanes.values() for lane in links.values()})


def _sumo_args(sumocfg: Path) -> list[str]:
    _ensure_sumo_home()
    return [
        _resolve_sumo_binary(), "-c", str(sumocfg),
        "--step-length", "1.0", "--no-step-log", "true",
        "--time-to-teleport", "300", "--seed", str(_SEED),
    ]


def standalone_probe(sumocfg: Path) -> bool:
    link_lanes = link_to_lane_map(_NET)
    schedule = random_schedule(
        _controlled_lanes(), seed=_INCIDENT_SEED, n_incidents=_N_INCIDENTS,
        run_ticks=_RUN_TICKS, duration_ticks_range=(45, 75),
        warmup_ticks=200, cooldown_ticks=200, min_gap_ticks=150,
    )
    print("\n-- standalone_probe -- scheduled incidents:")
    for p in schedule:
        print(f"   {p.kind:10s} lane={p.lane_id:22s} start={p.start_tick:4d} "
              f"dur={p.duration_ticks}")

    inj = IncidentInjector(schedule, link_lanes=link_lanes)
    watch = {p.lane_id for p in schedule}
    # {tick: {veh_id: speed}} for vehicles on any watched lane -- lets us pull
    # out the exact frozen vehicle's own speed trace afterwards, rather than a
    # lane aggregate that a normal red-light queue would also drive to zero.
    veh_speed: dict[int, dict[str, float]] = {}
    lane_max_speed: dict[str, dict[int, float]] = {ln: {} for ln in watch}

    traci.start(_sumo_args(sumocfg))
    try:
        step = 0
        while traci.simulation.getMinExpectedNumber() > 0 and step < _RUN_TICKS:
            traci.simulationStep()
            step += 1
            inj.tick(step)
            frame: dict[str, float] = {}
            for ln in watch:
                for v in traci.lane.getLastStepVehicleIDs(ln):
                    frame[v] = traci.vehicle.getSpeed(v)
                lane_max_speed[ln][step] = traci.lane.getMaxSpeed(ln)
            veh_speed[step] = frame
        inj.finalize(step)
    finally:
        traci.close()

    ok = True
    for w in inj.ground_truth():
        if not w.realised:
            print(f"   [skip] {w.kind} on {w.lane_id} never realised "
                  f"(lane stayed empty) -- not a failure, retry with another seed")
            continue
        a, b = w.actual_start_tick, w.end_tick or step
        if w.kind == "stall":
            # the frozen vehicle's own speed, tick by tick
            during = [veh_speed.get(t, {}).get(w.vehicle_id) for t in range(a, b)]
            seen = [s for s in during if s is not None]
            held = [s for s in seen if s <= 0.2]
            post = [veh_speed.get(t, {}).get(w.vehicle_id) for t in range(b, min(b + 30, step))]
            post_seen = [s for s in post if s is not None]
            recovered = (not post_seen) or max(post_seen) > 1.0  # moving again, or gone
            good = len(held) >= max(3, int(0.6 * len(seen))) and recovered
            print(f"   {'PASS' if good else 'FAIL'}  stall {w.lane_id} "
                  f"veh={w.vehicle_id} ticks {a}-{b}: held <=0.2 for {len(held)}/{len(seen)} obs, "
                  f"post-window {'gone' if not post_seen else f'max {max(post_seen):.1f} m/s'}")
            ok = ok and good
        else:  # lane_block
            during = [lane_max_speed[w.lane_id].get(t, 99) for t in range(a, b)]
            after = lane_max_speed[w.lane_id].get(min(b + 5, step), 0)
            before = lane_max_speed[w.lane_id].get(max(a - 5, 1), 0)
            good = max(during) <= 1.0 and abs(after - before) < 0.5 and before > 1.0
            print(f"   {'PASS' if good else 'FAIL'}  lane_block {w.lane_id} "
                  f"ticks {a}-{b}: max-speed during <= {max(during):.2f}, "
                  f"before={before:.1f} after={after:.1f}")
            ok = ok and good
    return ok


def through_runner(sumocfg: Path) -> bool:
    configs = load_configs(_NET)
    link_lanes = link_to_lane_map(_NET)
    schedule = random_schedule(
        _controlled_lanes(), seed=_INCIDENT_SEED, n_incidents=_N_INCIDENTS,
        run_ticks=_RUN_TICKS, duration_ticks_range=(45, 75),
        warmup_ticks=200, cooldown_ticks=200, min_gap_ticks=150,
    )
    inj = IncidentInjector(schedule, link_lanes=link_lanes)

    from sim_service.control.strategies import fixed_time

    result = run_controlled_scenario(
        str(sumocfg), configs, strategy=fixed_time.propose,
        seed=_SEED, link_lanes=link_lanes, max_steps=_RUN_TICKS,
        incident_injector=inj,
    )
    windows = inj.ground_truth()
    open_windows = [w for w in windows if w.realised and w.end_tick is None]
    bad_reason = [w for w in windows if w.realised and w.ended_reason
                  not in ("released", "run_ended", "vehicle_gone")]
    print("\n-- through_runner --")
    print(f"   steps={result['steps']}  interlock_violations={result['interlock_violations']}")
    for w in windows:
        print(f"   {w.kind:10s} {w.lane_id:22s} "
              f"{'unrealised' if not w.realised else f'{w.actual_start_tick}-{w.end_tick}'} "
              f"reason={w.ended_reason}")
    good = not open_windows and not bad_reason and result["interlock_violations"] == 0
    print(f"   {'PASS' if good else 'FAIL'}  "
          f"{len(open_windows)} still-open, {len(bad_reason)} bad-reason, "
          f"{result['interlock_violations']} interlock violations")
    return good


def main() -> None:
    suffix = sys.argv[1] if len(sys.argv) > 1 else "_light"
    sumocfg = _DEMAND / f"vijayawada_corridor{suffix}.sumocfg"
    print(f"demand: {suffix or '(medium)'} -- {sumocfg.name}")

    p1 = standalone_probe(sumocfg)
    p2 = through_runner(sumocfg)

    print("\n" + "=" * 60)
    print(f"standalone_probe : {'PASS' if p1 else 'FAIL'}")
    print(f"through_runner   : {'PASS' if p2 else 'FAIL'}")
    sys.exit(0 if (p1 and p2) else 1)


if __name__ == "__main__":
    main()
