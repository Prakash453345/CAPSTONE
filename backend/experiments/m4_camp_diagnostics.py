"""Diagnostic instrumentation for the M4 gate comparison's open question:
why does CA-MP lose to tuned Webster at light/medium demand, and why did
the hysteresis sweep (`m4_hysteresis_sweep.py`) come back bit-identical
across every value tested?

This script tests a specific, falsifiable hypothesis about the mechanism,
rather than continuing to guess: that the switching-cost term (§3.4 Term
6, `camp._switch`) is large enough relative to typical flow pressure at
light/medium demand that the currently-green phase's own pressure is
*already* the outright maximum among all candidates on every tick --
never a close call the hysteresis tolerance could have mattered for --
so the only thing that ever ends a green phase is hitting `max_green_s`,
turning CA-MP into a fixed-time-at-maximum-cycle controller in
disguise at low demand.

This is directly checkable without modifying `camp.py`: wrap each
junction's `camp.propose` call, and on every tick record (a) whether the
proposal is an EXTEND or an ADVANCE (1-step vs 2-step `SignalPlan`,
exactly how `propose` itself distinguishes them), (b) if it's an ADVANCE,
whether it happened because `elapsed >= max_green_s` (a timeout -- the
ring would have advanced no matter what pressure said) or because the
extend test failed early (a genuine pressure-driven decision), and (c)
the current phase's own raw flow pressure vs. the fixed switch-cost
constant it's being compared against, so the two can be read side by
side rather than assumed.

One seed per demand level -- this is a mechanism check, not a statistical
claim (that's what `m4_gate_comparison.py` already did 10 seeds of).

Not part of the pytest suite: shells out to real SUMO processes.
"""

from __future__ import annotations

import sys
import tempfile
from collections import Counter
from pathlib import Path

from itms_domain import JunctionContext, SignalPlan, Tier0Config
from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies import camp, webster
from sim_service.signal_controller.queue_state import load_vtype_pcu

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "data" / "scenarios" / "networks" / "vijayawada"))
from extract_tier0_config import load_configs  # noqa: E402
from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402

_NET_PATH = _ROOT / "data" / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
_DEMAND_DIR = _ROOT / "data" / "scenarios" / "demand" / "vijayawada"
_SEED = 1

_DEMAND_LEVELS: dict[str, dict[str, Path]] = {
    "light": {
        "sumocfg": _DEMAND_DIR / "vijayawada_corridor_light.sumocfg",
        "route": _DEMAND_DIR / "vijayawada_corridor_light.rou.xml",
    },
    "medium": {
        "sumocfg": _DEMAND_DIR / "vijayawada_corridor.sumocfg",
        "route": _DEMAND_DIR / "vijayawada_corridor.rou.xml",
    },
    "heavy": {
        "sumocfg": _DEMAND_DIR / "vijayawada_corridor_heavy.sumocfg",
        "route": _DEMAND_DIR / "vijayawada_corridor_heavy.rou.xml",
    },
}

_link_lanes = link_to_lane_map(_NET_PATH)
_receiving_lanes = link_to_receiving_lane_map(_NET_PATH)


class _Instrumented:
    """Wraps one junction's `camp.propose` to classify every tick without
    touching `camp.py` itself. Mirrors `propose`'s own extend/advance
    branching exactly (see its docstring) so the classification is
    provably reading the same decision the real strategy made, not a
    re-implementation that could quietly diverge from it."""

    def __init__(self, cfg: Tier0Config, camp_cfg: camp.CampConfig, nominal_cycle_s: float):
        self.cfg = cfg
        self.camp_cfg = camp_cfg
        self.nominal_cycle_s = nominal_cycle_s
        self.counts: Counter[str] = Counter()
        self.flow_pressures: list[float] = []
        self.switch_costs: list[float] = []
        self.current_was_outright_max: Counter[str] = Counter()

    def __call__(self, cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan:
        current = ctx.current_phase_id
        elapsed = ctx.current_phase_elapsed_s
        max_g = cfg.max_green_s.get(current, 0.0)
        min_g = cfg.min_green_s.get(current, 0.0)

        live_phases = [p for p in cfg.ring_order if p not in ctx.faulted_phases]
        if live_phases and elapsed >= min_g:
            pressures = {p: camp.pressure(self.camp_cfg, cfg, ctx, p) for p in live_phases}
            if current in pressures:
                best = max(pressures.values())
                self.flow_pressures.append(camp._flow_pressure(cfg, ctx, current))
                # any other live phase gives the same switch-cost constant
                other = next((p for p in live_phases if p != current), None)
                if other is not None:
                    self.switch_costs.append(
                        camp._switch(self.camp_cfg, cfg, current, other)
                    )
                if pressures[current] >= best:
                    self.current_was_outright_max["yes"] += 1
                else:
                    self.current_was_outright_max["no"] += 1

        plan = camp.propose(
            cfg, ctx, camp_cfg=self.camp_cfg, nominal_cycle_s=self.nominal_cycle_s
        )

        if len(plan.steps) == 1:
            self.counts["extend"] += 1
        else:
            if elapsed >= max_g:
                self.counts["advance_timeout"] += 1
            else:
                self.counts["advance_pressure_driven"] += 1
        return plan


def main() -> None:
    configs = load_configs(_NET_PATH)

    for level, paths in _DEMAND_LEVELS.items():
        flows = compute_link_flows(_NET_PATH, paths["route"])
        vtype_pcu = load_vtype_pcu(paths["route"])

        instrumented: dict[str, _Instrumented] = {}
        strategy = {}
        for tls_id, cfg in configs.items():
            timing = webster.compute_timing(cfg, flows.get(tls_id, {}))
            camp_cfg = camp.CampConfig(enable_blocking=True)
            wrapper = _Instrumented(cfg, camp_cfg, timing.cycle_s)
            instrumented[tls_id] = wrapper
            strategy[tls_id] = wrapper

        with tempfile.TemporaryDirectory(prefix="itms_m4_diag_") as tmp_dir:
            tripinfo_path = Path(tmp_dir) / f"{level}.tripinfo.xml"
            result = run_controlled_scenario(
                str(paths["sumocfg"]),
                configs,
                strategy=strategy,
                seed=_SEED,
                link_lanes=_link_lanes,
                receiving_lanes=_receiving_lanes,
                vtype_pcu=vtype_pcu,
                tripinfo_output=str(tripinfo_path),
            )

        print(f"\n=== {level} demand (seed={_SEED}) ===")
        print(f"  steps={result['steps']} interlock_violations={result['interlock_violations']}")

        total_counts: Counter[str] = Counter()
        total_outright: Counter[str] = Counter()
        all_flow: list[float] = []
        all_switch: list[float] = []
        for w in instrumented.values():
            total_counts.update(w.counts)
            total_outright.update(w.current_was_outright_max)
            all_flow.extend(w.flow_pressures)
            all_switch.extend(w.switch_costs)

        n_advances = total_counts["advance_timeout"] + total_counts["advance_pressure_driven"]
        pct_timeout = (
            100.0 * total_counts["advance_timeout"] / n_advances if n_advances else float("nan")
        )
        n_outright = total_outright["yes"] + total_outright["no"]
        pct_outright = (
            100.0 * total_outright["yes"] / n_outright if n_outright else float("nan")
        )
        mean_flow = sum(all_flow) / len(all_flow) if all_flow else float("nan")
        mean_switch = sum(all_switch) / len(all_switch) if all_switch else float("nan")

        print(f"  phase changes: {n_advances} total "
              f"({total_counts['advance_timeout']} by max_green timeout, "
              f"{total_counts['advance_pressure_driven']} pressure-driven early exit)")
        print(f"  -> {pct_timeout:.1f}% of phase changes were pure max_green timeouts")
        print(f"  current phase was the outright pressure max on "
              f"{pct_outright:.1f}% of extend-eligible ticks "
              f"(n={n_outright}) -- hysteresis can only matter on the rest")
        print(f"  mean current-phase flow pressure (P_flow): {mean_flow:.2f}")
        print(f"  fixed switch-cost constant (S(p) for p != current): {mean_switch:.2f}")
        if mean_switch:
            print(f"  switch cost as a fraction of typical flow pressure: "
                  f"{100.0 * mean_switch / mean_flow:.0f}%" if mean_flow else "  (mean_flow is 0)")


if __name__ == "__main__":
    main()
