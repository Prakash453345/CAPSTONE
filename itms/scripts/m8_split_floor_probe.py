"""Probe: a design-split floor for CC-A-CAMP under congestion (M8 heavy jams).

At heavy demand the corridor's four-phase junction
(`cluster_1880441740_4393296791`) runs at Webster degree of saturation 0.996:
every phase needs its share of the cycle, and a phase that gets less for a
while builds a queue it cannot pay back. Traces of the bad runs (perfect data
and cameras alike) show phase P2 -- one approach lane, max green 28.6 s --
served less often and shorter while P0/P1 run long.

The probe gives every phase, when the junction is congested (the same
congestion weight `protect_allocated_green` already uses), an allocation of at
least `floor` x its Webster design green, so the existing allocation
protection holds it that long while it still has demand. Nothing changes
below the congestion threshold. Library code is untouched: the floor is a
subclass here, run on ground truth on TRAIN seeds.

    python scripts/m8_split_floor_probe.py --level heavy --floors 0,1.0 \\
        --seeds 101,102,103 --out results/m8_split_floor_probe.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m8_harness as M  # noqa: E402
from m5_ccacamp_gate import _ARMS  # noqa: E402
from sim_service.control import memory as memory_mod  # noqa: E402
from sim_service.control.strategies import acamp, webster  # noqa: E402


class FlooredCamp(acamp.AdaptiveCamp):
    def __init__(self, *a, design_green_s: dict, floor: float, **kw):
        super().__init__(*a, **kw)
        self.design_green_s = design_green_s
        self.floor = floor
        self.floored = 0

    def _advance(self, cfg_t0, ctx, current, next_phase, pressures, min_g):
        plan = super()._advance(cfg_t0, ctx, current, next_phase, pressures, min_g)
        if self.floor > 0:
            congestion = memory_mod.congestion_weight(
                self._load_ewma, self.cfg.switch_scale_ref, self.cfg.switch_scale_exponent)
            if congestion >= self.cfg.protect_allocated_green_congestion_threshold:
                want = min(cfg_t0.max_green_s.get(next_phase, 1e9),
                           self.floor * self.design_green_s.get(next_phase, 0.0))
                if want > self._current_phase_allocation_s:
                    self._current_phase_allocation_s = want
                    self.floored += 1
        return plan


def build(level: str, floor: float):
    inputs = M.ccacamp_inputs(level)
    configs, flows, _, _ = inputs
    out = {}
    for tls, cfg in configs.items():
        tm = webster.compute_timing(cfg, flows.get(tls, {}))
        out[tls] = FlooredCamp(_ARMS["ccacamp"], nominal_cycle_s=tm.cycle_s,
                               design_green_s=dict(tm.green_s), floor=floor)
    return inputs, out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="heavy")
    ap.add_argument("--floors", default="0,1.0")
    ap.add_argument("--seeds", default="101,102,103,104,105,106,107,108,109,110")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    floors = [float(f) for f in args.floors.split(",")]
    seeds = [int(s) for s in args.seeds.split(",")]
    rows = []
    for seed in seeds:
        for floor in floors:
            inputs, strat = build(args.level, floor)
            r = M.run_scenario("ccacamp", args.level, seed, inputs=inputs, strategy=strat,
                               tag=f"floor{floor}")
            rows.append({"seed": seed, "floor": floor, "person_delay_s": r["person_delay_s"],
                         "max_wait_s": r["wait_time_s"]["max_s"], "steps": r["steps"],
                         "violations": r["interlock_violations"],
                         "floored": sum(s.floored for s in strat.values())})
            print(json.dumps(rows[-1]), flush=True)
            Path(args.out).write_text(json.dumps(rows, indent=1))
    for floor in floors:
        v = [r["person_delay_s"] for r in rows if r["floor"] == floor]
        print(f"floor {floor}: mean {st.fmean(v):,.0f}  max {max(v):,.0f}")


if __name__ == "__main__":
    main()
