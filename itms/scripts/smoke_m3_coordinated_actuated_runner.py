"""End-to-end smoke test for the coordinated-actuated strategy against the
real Vijayawada corridor -- the fourth and last of this shape (after
fixed_time, Webster, and semi-actuated). This one exercises the part
unique to coordination: a real shared cycle and real travel-time offsets
(`corridor_geometry.py` + `coordinated_actuated.build_corridor_plan`)
driving all 7 real junctions against one absolute clock
(`traci.simulation.getTime()`), not just each junction's own local state.

`coordinated_actuated.propose` needs `system_time_s` on every call, unlike
every earlier strategy -- built here as a small per-junction closure that
reads the clock itself, since `run_controlled_scenario`'s `Strategy` type
is `Callable[[Tier0Config, JunctionContext], SignalPlan]` and doesn't pass
sim time through.

Not part of the pytest suite for the same reason the other three smoke
scripts aren't: it shells out to a real SUMO process.
"""

from __future__ import annotations

import sys
from pathlib import Path

import traci
from itms_domain import JunctionContext, SignalPlan, Tier0Config
from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies import coordinated_actuated as ca

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scenarios" / "networks" / "vijayawada"))
from corridor_geometry import corridor_order, cumulative_distances_m  # noqa: E402
from extract_tier0_config import load_configs  # noqa: E402
from link_lanes import link_to_lane_map  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402


def _make_strategy(coordination: ca.CoordinationPlan):
    def strategy(cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan:
        return ca.propose(
            cfg, ctx, coordination=coordination, system_time_s=traci.simulation.getTime()
        )

    return strategy


def main() -> None:
    net_path = _ROOT / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
    sumocfg_path = _ROOT / "scenarios" / "demand" / "vijayawada" / "vijayawada_corridor.sumocfg"

    configs = load_configs(net_path)
    flows = compute_link_flows()
    link_lanes = link_to_lane_map(net_path)
    distances_m = cumulative_distances_m(net_path)
    order = corridor_order(net_path)
    print(f"corridor order: {order}")

    plans = ca.build_corridor_plan(configs, flows, distances_m)
    for tls_id in order:
        p = plans[tls_id]
        print(
            f"  {tls_id}: cycle={p.cycle_s:.1f}s offset={p.offset_s:.1f}s "
            f"coord_phase={p.coordinated_phase_id} coord_green={p.coordinated_green_s:.1f}s"
        )

    per_junction_strategy = {tls_id: _make_strategy(plans[tls_id]) for tls_id in configs}

    result = run_controlled_scenario(
        str(sumocfg_path),
        configs,
        strategy=per_junction_strategy,
        seed=1,
        link_lanes=link_lanes,
    )
    print(f"steps run: {result['steps']}")
    print(f"interlock_violations: {result['interlock_violations']}")
    print(f"fault_events: {result['fault_events']}")

    if result["interlock_violations"] != 0:
        raise SystemExit(f"FAIL: {result['interlock_violations']} interlock violations")
    if result["fault_events"]:
        raise SystemExit(f"FAIL: unexpected fault events: {result['fault_events']}")
    print("PASS: zero interlock violations, zero fault events, over", result["steps"], "steps")


if __name__ == "__main__":
    main()
