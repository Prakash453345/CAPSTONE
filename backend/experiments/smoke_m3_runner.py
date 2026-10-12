"""One-off smoke test for `control.runner.run_controlled_scenario`, run
against the real Vijayawada corridor scenario with `fixed_time.propose` as
the governing strategy. Not part of the pytest suite (it shells out to a
real SUMO process for ~120 sim-seconds, deliberately capped short here just
to confirm the arbiter takes zero failsafe/interlock branches through the
full TraCI-integrated path) -- the M3 gate's actual `make bench` will run
full-length, multi-seed sweeps; this is narrower: did the
`Phase.protected_movements` fix carry through end-to-end.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies.fixed_time import propose

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "data" / "scenarios" / "networks" / "vijayawada"))
from extract_tier0_config import load_configs  # noqa: E402


def main() -> None:
    net_path = _ROOT / "data" / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
    sumocfg_path = _ROOT / "data" / "scenarios" / "demand" / "vijayawada" / "vijayawada_corridor.sumocfg"

    configs = load_configs(net_path)
    print(f"loaded {len(configs)} junction configs: {sorted(configs)}")

    result = run_controlled_scenario(
        str(sumocfg_path),
        configs,
        strategy=propose,
        seed=1,
        max_steps=120,
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
