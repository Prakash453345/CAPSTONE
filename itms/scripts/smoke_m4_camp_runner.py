"""End-to-end smoke test for CA-MP (M4) against the real Vijayawada
corridor -- the same shape as the M3 smoke scripts
(`smoke_m3_semi_actuated_runner.py`, `smoke_m3_coordinated_actuated_runner.py`),
now exercising what's unique to CA-MP: real PCU-weighted queues and real
receiving-link occupancy, via `QueueStateSampler` wired into
`run_controlled_scenario`'s `receiving_lanes`/`vtype_pcu` parameters
(alongside `link_lanes`, which CA-MP also needs for `wait_times_s`/
`has_demand` -- see `camp.py`'s `_skippable`/`_fairness`).

`nominal_cycle_s` per junction comes from `webster.compute_timing`'s own
tuned cycle -- the same "tie the duration-allocation heuristic back to
already-measured flow data" choice `camp.py`'s own docstring commits to,
not a second invented constant.

Usage: `python smoke_m4_camp_runner.py [demand_suffix]`, e.g. `_light` or
`_heavy` (see `build_demand_levels.sh`) to run against a different
demand level's `vijayawada_corridor{suffix}.sumocfg`/`.rou.xml` instead of
the default medium demand -- the M4 gate needs this run repeated at all
3 levels, not just one.

Not part of the pytest suite for the same reason the other smoke scripts
aren't: it shells out to a real SUMO process.
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies import camp, webster
from sim_service.signal_controller.queue_state import load_vtype_pcu

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scenarios" / "networks" / "vijayawada"))
from extract_tier0_config import load_configs  # noqa: E402
from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402


def main() -> None:
    suffix = sys.argv[1] if len(sys.argv) > 1 else ""
    demand_dir = _ROOT / "scenarios" / "demand" / "vijayawada"
    net_path = _ROOT / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
    sumocfg_path = demand_dir / f"vijayawada_corridor{suffix}.sumocfg"
    route_path = demand_dir / f"vijayawada_corridor{suffix}.rou.xml"
    print(f"demand level: {suffix or '(medium, default)'} -- {route_path.name}")

    configs = load_configs(net_path)
    flows = compute_link_flows(net_path, route_path)
    link_lanes = link_to_lane_map(net_path)
    receiving_lanes = link_to_receiving_lane_map(net_path)
    vtype_pcu = load_vtype_pcu(route_path)
    print(f"loaded {len(configs)} junction configs")
    print(f"vtype PCU table: {vtype_pcu}")

    per_junction_strategy = {}
    for tls_id, cfg in configs.items():
        timing = webster.compute_timing(cfg, flows.get(tls_id, {}))
        per_junction_strategy[tls_id] = partial(camp.propose, nominal_cycle_s=timing.cycle_s)
        print(f"  {tls_id}: nominal_cycle_s = {timing.cycle_s:.1f}s")

    result = run_controlled_scenario(
        str(sumocfg_path),
        configs,
        strategy=per_junction_strategy,
        seed=1,
        link_lanes=link_lanes,
        receiving_lanes=receiving_lanes,
        vtype_pcu=vtype_pcu,
        spillback_lane_ids=[lane for lanes in link_lanes.values() for lane in lanes.values()],
    )
    print(f"steps run: {result['steps']}")
    print(f"interlock_violations: {result['interlock_violations']}")
    print(f"fault_events: {result['fault_events']}")
    print(f"spillback_events: {result['spillback_events']}")

    if result["interlock_violations"] != 0:
        raise SystemExit(f"FAIL: {result['interlock_violations']} interlock violations")
    if result["fault_events"]:
        raise SystemExit(f"FAIL: unexpected fault events: {result['fault_events']}")
    print("PASS: zero interlock violations, zero fault events, over", result["steps"], "steps")


if __name__ == "__main__":
    main()
