"""End-to-end smoke test for the semi-actuated strategy against the real
Vijayawada corridor -- the third proof of this shape this chunk builds
(after `smoke_m3_runner.py` for fixed_time and `smoke_m3_webster_runner.py`
for Webster). This one exercises the part unique to semi-actuated: real
lane-level demand, via `link_lanes.link_to_lane_map()` wired into
`run_controlled_scenario`'s new `link_lanes` parameter, driving a live
`ActuationDetector` per junction -- not just a hand-built synthetic
`JunctionContext` the way the Hypothesis suite does.

Not part of the pytest suite for the same reason the other two smoke
scripts aren't: it shells out to a real SUMO process.
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies import semi_actuated, webster

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "data" / "scenarios" / "networks" / "vijayawada"))
from extract_tier0_config import load_configs  # noqa: E402
from link_lanes import link_to_lane_map  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402


def main() -> None:
    net_path = _ROOT / "data" / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
    sumocfg_path = _ROOT / "data" / "scenarios" / "demand" / "vijayawada" / "vijayawada_corridor.sumocfg"

    configs = load_configs(net_path)
    flows = compute_link_flows()
    link_lanes = link_to_lane_map(net_path)
    print(f"loaded {len(configs)} junction configs, lane maps for {len(link_lanes)} of them")

    # Major phase per junction: the busiest phase by measured critical flow
    # ratio (webster.compute_timing already derives exactly that number).
    major_phases = {}
    for tls_id, cfg in configs.items():
        timing = webster.compute_timing(cfg, flows.get(tls_id, {}))
        major_phases[tls_id] = semi_actuated.pick_major_phase(timing.critical_flow_ratios)
        print(f"  {tls_id}: major phase = {major_phases[tls_id]}")

    per_junction_strategy = {
        tls_id: partial(semi_actuated.propose, major_phase_id=major_phases[tls_id])
        for tls_id in configs
    }

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
