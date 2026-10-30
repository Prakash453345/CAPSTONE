"""End-to-end smoke test for the tuned Webster strategy against the real
Vijayawada corridor -- the same proof `smoke_m3_runner.py` gave
`fixed_time.propose`, but exercising the part that's actually new this
chunk: a *per-junction* strategy built from that junction's own measured
flows (`measure_flows.py`) and its own `Tier0Config` (`webster.compute_timing`),
routed through `runner.run_controlled_scenario`'s widened `StrategySource`
(a `Mapping[str, Strategy]` now, not just one uniform callable -- see that
module's docstring for why Webster needed that).

Not part of the pytest suite for the same reason `smoke_m3_runner.py`
isn't: it shells out to a real SUMO process.
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies import webster

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "data" / "scenarios" / "networks" / "vijayawada"))
from extract_tier0_config import load_configs  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402


def main() -> None:
    net_path = _ROOT / "data" / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
    sumocfg_path = _ROOT / "data" / "scenarios" / "demand" / "vijayawada" / "vijayawada_corridor.sumocfg"

    configs = load_configs(net_path)
    flows = compute_link_flows()
    print(f"loaded {len(configs)} junction configs, measured flows for {len(flows)} of them")

    timings = {
        tls_id: webster.compute_timing(cfg, flows.get(tls_id, {}))
        for tls_id, cfg in configs.items()
    }
    for tls_id, timing in sorted(timings.items()):
        greens = ", ".join(f"{p}={g:.1f}s" for p, g in timing.green_s.items())
        print(
            f"  {tls_id}: cycle={timing.cycle_s:.1f}s "
            f"Y={timing.degree_of_saturation:.2f} greens=[{greens}]"
        )

    # One bound `propose` per junction, closing over that junction's own
    # tuned timing -- exactly what `StrategySource`'s Mapping branch exists
    # for (see runner.py).
    per_junction_strategy = {
        tls_id: partial(webster.propose, timing=timings[tls_id]) for tls_id in configs
    }

    result = run_controlled_scenario(
        str(sumocfg_path),
        configs,
        strategy=per_junction_strategy,
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
