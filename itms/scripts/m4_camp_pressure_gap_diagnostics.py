"""Follow-up to `m4_camp_diagnostics.py`'s finding that the currently-green
phase is the outright pressure max on 100.0% of extend-eligible ticks at
*every* demand level, even at heavy demand where `S(p)` finally averaged
below `P_flow` (92%) -- PROGRESS.md's "Re-ran the sweep and the gate
comparison" section flags that a mean-vs-mean ratio is too coarse a proxy
to explain a 100.0% result and that the honest next step is the *actual*
per-tick pressure comparison `propose()` makes, not another mean.

This script answers one falsifiable question directly, per tick, at every
junction: is `S(p)` -- the switching-cost term -- what's actually keeping
CA-MP from switching, or would the *other three* terms (flow, block,
fairness) already favour staying even with the switch cost zeroed out?

For every extend-eligible tick, compute two pressure rankings against the
live phases:

  raw(p)    = P_flow(p) - P_block(p) + F(p)            (§3.4 minus S(p))
  full(p)   = raw(p) - S(p)                             (what propose() uses)

and classify the tick by comparing `current` against the best *other*
live phase under each ranking:

  - "current_genuinely_best": best raw(p) among p != current does not
    exceed raw(current) -- current would still be the top pick even with
    switching priced at zero. S(p) isn't the reason CA-MP stays; the
    underlying flow/block/fairness signal already agrees with staying.
  - "switch_cost_is_deciding": some other phase's raw(p) exceeds
    raw(current) (so absent S(p), CA-MP would have switched), but once
    S(p) is subtracted its full(p) no longer exceeds full(current). S(p)
    is the term actively suppressing a switch the rest of the formula
    wanted to make.
  - "would_switch_anyway": some other phase's full(p) exceeds
    full(current) even with S(p) included -- i.e. a genuine pressure-
    driven switch (this is the tiny nonzero slice `m4_camp_diagnostics.py`
    already found: 3/169, 0/161, 1/245 phase changes at light/medium/heavy).

One seed per demand level -- a mechanism check, not a statistical claim,
exactly like `m4_camp_diagnostics.py`'s own scope note.

Not part of the pytest suite: shells out to real SUMO processes.
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
from collections import Counter
from pathlib import Path

from itms_domain import JunctionContext, SignalPlan, Tier0Config
from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies import camp, webster
from sim_service.signal_controller.queue_state import load_vtype_pcu

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scenarios" / "networks" / "vijayawada"))
from extract_tier0_config import load_configs  # noqa: E402
from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402

_NET_PATH = _ROOT / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
_DEMAND_DIR = _ROOT / "scenarios" / "demand" / "vijayawada"
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


def _raw_pressure(camp_cfg: camp.CampConfig, cfg: Tier0Config, ctx: JunctionContext, phase_id: str) -> float:
    """§3.4's flow/block/fairness terms only -- `pressure()` minus S(p)."""
    block = camp._block_pressure(camp_cfg, cfg, ctx, phase_id) if camp_cfg.enable_blocking else 0.0
    return camp._flow_pressure(cfg, ctx, phase_id) - block + camp._fairness(camp_cfg, cfg, ctx, phase_id)


class _GapInstrumented:
    """Wraps one junction's `camp.propose` to classify every extend-
    eligible tick by whether S(p) is actually the deciding term. Mirrors
    `propose`'s own extend-eligibility gate (`elapsed >= min_g`) so this
    reads the same population of ticks `_Instrumented` in
    `m4_camp_diagnostics.py` does."""

    def __init__(self, cfg: Tier0Config, camp_cfg: camp.CampConfig, nominal_cycle_s: float):
        self.cfg = cfg
        self.camp_cfg = camp_cfg
        self.nominal_cycle_s = nominal_cycle_s
        self.counts: Counter[str] = Counter()
        self.suppressed_gaps: list[float] = []  # raw(best) - raw(current) when S(p) is deciding

    def __call__(self, cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan:
        current = ctx.current_phase_id
        elapsed = ctx.current_phase_elapsed_s
        min_g = cfg.min_green_s.get(current, 0.0)
        live_phases = [p for p in cfg.ring_order if p not in ctx.faulted_phases]

        if live_phases and elapsed >= min_g and current in live_phases:
            others = [p for p in live_phases if p != current]
            if others:
                raw = {p: _raw_pressure(self.camp_cfg, cfg, ctx, p) for p in live_phases}
                full = {p: camp.pressure(self.camp_cfg, cfg, ctx, p) for p in live_phases}

                best_raw_other = max(others, key=lambda p: raw[p])
                best_full_other = max(others, key=lambda p: full[p])

                raw_gap = raw[best_raw_other] - raw[current]
                full_gap = full[best_full_other] - full[current]

                if raw_gap <= 0:
                    self.counts["current_genuinely_best"] += 1
                elif full_gap > 0:
                    self.counts["would_switch_anyway"] += 1
                else:
                    self.counts["switch_cost_is_deciding"] += 1
                    self.suppressed_gaps.append(raw_gap)

        return camp.propose(cfg, ctx, camp_cfg=self.camp_cfg, nominal_cycle_s=self.nominal_cycle_s)


def main() -> None:
    configs = load_configs(_NET_PATH)
    pooled_gaps: list[float] = []
    per_level_gaps: dict[str, list[float]] = {}

    for level, paths in _DEMAND_LEVELS.items():
        flows = compute_link_flows(_NET_PATH, paths["route"])
        vtype_pcu = load_vtype_pcu(paths["route"])

        instrumented: dict[str, _GapInstrumented] = {}
        strategy = {}
        for tls_id, cfg in configs.items():
            timing = webster.compute_timing(cfg, flows.get(tls_id, {}))
            camp_cfg = camp.CampConfig(enable_blocking=True)
            wrapper = _GapInstrumented(cfg, camp_cfg, timing.cycle_s)
            instrumented[tls_id] = wrapper
            strategy[tls_id] = wrapper

        with tempfile.TemporaryDirectory(prefix="itms_m4_gapdiag_") as tmp_dir:
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

        total: Counter[str] = Counter()
        all_suppressed: list[float] = []
        for w in instrumented.values():
            total.update(w.counts)
            all_suppressed.extend(w.suppressed_gaps)

        n = sum(total.values())
        if n == 0:
            print("  no extend-eligible ticks recorded")
            continue

        for key in ("current_genuinely_best", "switch_cost_is_deciding", "would_switch_anyway"):
            pct = 100.0 * total[key] / n
            print(f"  {key}: {total[key]} ({pct:.2f}%)")

        if all_suppressed:
            mean_suppressed = sum(all_suppressed) / len(all_suppressed)
            print(
                f"  mean suppressed raw pressure gap (how far ahead the best "
                f"alternative was, before S(p) pulled it back): {mean_suppressed:.4f}"
            )
            print(f"  max suppressed raw pressure gap: {max(all_suppressed):.4f}")
            quantiles = statistics.quantiles(all_suppressed, n=20, method="inclusive")
            # quantiles[9] = 50th pct (median), [14] = 75th, [17] = 90th, [18] = 95th
            print(
                f"  percentiles of positive raw-gap population (n={len(all_suppressed)}): "
                f"p50={quantiles[9]:.4f} p75={quantiles[14]:.4f} "
                f"p90={quantiles[17]:.4f} p95={quantiles[18]:.4f}"
            )
            per_level_gaps[level] = all_suppressed
            pooled_gaps.extend(all_suppressed)
        else:
            print("  S(p) never once flipped a decision that raw pressure already favored")

    if pooled_gaps:
        print(f"\n=== pooled across all 3 demand levels (n={len(pooled_gaps)}) ===")
        pooled_quantiles = statistics.quantiles(pooled_gaps, n=20, method="inclusive")
        print(
            f"  p50={pooled_quantiles[9]:.4f} p75={pooled_quantiles[14]:.4f} "
            f"p90={pooled_quantiles[17]:.4f} p95={pooled_quantiles[18]:.4f} "
            f"max={max(pooled_gaps):.4f}"
        )
        out_path = Path(__file__).resolve().parent / "results" / "m4_camp_pressure_gap_raw.json"
        out_path.write_text(json.dumps(per_level_gaps))
        print(f"  raw values written to {out_path}")


if __name__ == "__main__":
    main()
