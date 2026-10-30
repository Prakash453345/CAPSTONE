"""Why does A-CA-MP lose at heavy demand? Instrument a real heavy run and
find out, rather than reasoning from the algebra alone.

Two hypotheses, which predict different signatures:

**H1 -- over-switching.** `F(scale) = κ·scale^α` with the tuned
`α = 0.11` grows so slowly that switching resistance collapses *relative*
to pressure differences under load (`F/ΔP -> 0`). Predicts: many more
phase changes than the untuned arm, most of them pressure-driven, and
mean green durations well above `min_green`.

**H2 -- green allocation collapse.** At heavy demand receiving links are
congested, so `− r_m` dominates and every phase's pressure goes negative
at once. `allocate_green` takes the *positive part* of each pressure, so
when they are all negative its total is zero and it returns `min_green_s`
for whichever phase is chosen. Every phase then runs its bare minimum,
which maximizes the number of clearance intervals paid per hour exactly
when lost time is most expensive. Predicts: mean green pinned at
`min_green`, and a high fraction of ticks where `max 𝒫 <= 0`.

The two are not exclusive and H2 would *cause* part of H1, which is
precisely why counting switches alone cannot separate them -- the
`all_pressures_negative` fraction is the discriminating measurement.

Instruments by wrapping the controller, not by editing `acamp.py`: the
thing under investigation must be the thing that ran in the gate.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from itms_domain import JunctionContext, SignalPlan, Tier0Config  # noqa: E402
from sim_service.control.strategies import acamp  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402


class Probe:
    """Wraps one junction's controller and records what its pressure
    function actually saw and did."""

    def __init__(self, inner: acamp.AdaptiveCamp):
        self.inner = inner
        self.ticks = 0
        self.all_negative_ticks = 0
        self.max_pressure_samples: list[float] = []
        self.spread_samples: list[float] = []
        self.hold_bias_samples: list[float] = []
        self.scale_samples: list[float] = []
        self.gate_samples: list[float] = []
        self.green_allocations: list[float] = []
        self.min_green_allocations = 0
        self.greens_served: list[float] = []
        self._current = None
        self._elapsed = 0.0

    def set_sim_time(self, t: float) -> None:
        self.inner.set_sim_time(t)

    @property
    def stats(self):
        return self.inner.stats

    def __call__(self, cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan:
        self.ticks += 1
        acfg = self.inner.cfg
        live = [p for p in cfg.ring_order if p not in ctx.faulted_phases]
        if live:
            pressures = {p: acamp.pressure(cfg, ctx, acfg, p) for p in live}
            vals = list(pressures.values())
            top = max(vals)
            self.max_pressure_samples.append(top)
            self.spread_samples.append(top - min(vals))
            if top <= 0.0:
                self.all_negative_ticks += 1
            scale = acamp.pressure_scale(cfg, ctx, acfg)
            self.scale_samples.append(scale)
            from sim_service.control.memory import sublinear_hold_bias

            self.hold_bias_samples.append(
                sublinear_hold_bias(scale, acfg.kappa_switch, acfg.alpha_switch)
            )
            for m in ctx.receiving_occupancy:
                self.gate_samples.append(acamp.gate(ctx.receiving_occupancy[m], acfg))

        plan = self.inner(cfg, ctx)

        # Green actually committed when a transition is proposed.
        if len(plan.steps) == 2:
            nxt = plan.steps[1]
            self.green_allocations.append(nxt.green_s)
            if abs(nxt.green_s - cfg.min_green_s.get(nxt.phase_id, 0.0)) < 1e-6:
                self.min_green_allocations += 1
            if self._current is not None:
                self.greens_served.append(self._elapsed)
            self._current = nxt.phase_id
            self._elapsed = 0.0
        else:
            self._elapsed += plan.steps[0].green_s if plan.steps else 0.0
        return plan


def _pct(a: int, b: int) -> str:
    return f"{(100.0 * a / b if b else 0.0):5.1f}%"


def run(level: str, seed: int, cfg_path: str | None, label: str) -> dict:
    inputs = H.scenario_inputs(level)
    configs, flows, _, _ = inputs
    acfg = load_config(cfg_path) if cfg_path else None
    inner = H.build_acamp(configs, flows, acamp_cfg=acfg)
    probes = {tls: Probe(c) for tls, c in inner.items()}

    original = H.CONTROLLERS["acamp"]
    H.CONTROLLERS["acamp"] = lambda *a, **k: probes
    try:
        record = H.run_one("acamp", level, seed, tripinfo_dir=Path("/tmp/m5_diag"), inputs=inputs)
    finally:
        H.CONTROLLERS["acamp"] = original

    ticks = sum(p.ticks for p in probes.values())
    all_neg = sum(p.all_negative_ticks for p in probes.values())
    allocs = [g for p in probes.values() for g in p.green_allocations]
    min_allocs = sum(p.min_green_allocations for p in probes.values())
    served = [g for p in probes.values() for g in p.greens_served]
    gates = [g for p in probes.values() for g in p.gate_samples]
    spreads = [s for p in probes.values() for s in p.spread_samples]
    biases = [b for p in probes.values() for b in p.hold_bias_samples]
    scales = [s for p in probes.values() for s in p.scale_samples]
    st = Counter()
    for p in probes.values():
        st.update(p.stats)

    out = {
        "label": label,
        "level": level,
        "seed": seed,
        "person_delay_s": record["person_delay_s"],
        "interlock_violations": record["interlock_violations"],
        "steps": record["steps"],
        "ticks": ticks,
        "all_pressures_negative_pct": 100.0 * all_neg / ticks if ticks else 0.0,
        "phase_changes": len(allocs),
        "alloc_at_min_green_pct": 100.0 * min_allocs / len(allocs) if allocs else 0.0,
        "mean_green_allocated_s": statistics.mean(allocs) if allocs else 0.0,
        "mean_green_served_s": statistics.mean(served) if served else 0.0,
        "median_gate": statistics.median(gates) if gates else 0.0,
        "mean_pressure_spread": statistics.mean(spreads) if spreads else 0.0,
        "mean_hold_bias": statistics.mean(biases) if biases else 0.0,
        "mean_scale": statistics.mean(scales) if scales else 0.0,
        "bias_over_spread": (
            statistics.mean(biases) / statistics.mean(spreads)
            if spreads and statistics.mean(spreads) > 0
            else float("inf")
        ),
        "decisions": dict(st),
    }
    print(
        f"\n=== {label} | {level} seed {seed} ===\n"
        f"  person delay            {out['person_delay_s']:>14,.0f}\n"
        f"  interlock violations    {out['interlock_violations']:>14d}\n"
        f"  phase changes           {out['phase_changes']:>14d}\n"
        f"  mean green served       {out['mean_green_served_s']:>14.1f} s\n"
        f"  mean green allocated    {out['mean_green_allocated_s']:>14.1f} s\n"
        f"  allocation == min_green {out['alloc_at_min_green_pct']:>13.1f}%   <-- H2\n"
        f"  all pressures <= 0      {out['all_pressures_negative_pct']:>13.1f}%   <-- H2\n"
        f"  median gate(rho)        {out['median_gate']:>14.3f}\n"
        f"  mean pressure spread    {out['mean_pressure_spread']:>14.2f}\n"
        f"  mean hold bias          {out['mean_hold_bias']:>14.2f}\n"
        f"  bias / spread           {out['bias_over_spread']:>14.3f}   <-- H1\n"
        f"  decisions               {out['decisions']}",
        flush=True,
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="heavy")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument(
        "--out", default=str(Path(__file__).resolve().parent / "results" / "m5_heavy_diag.json")
    )
    args = ap.parse_args()

    tuned = str(Path(__file__).resolve().parent / "results" / "m5_artifacts" / "acamp_tuned.json")
    results = [
        run(args.level, args.seed, None, "acamp-default"),
        run(args.level, args.seed, tuned, "acamp-tuned"),
    ]
    # Light demand for contrast -- the regime A-CA-MP wins in.
    results.append(run("light", args.seed, tuned, "acamp-tuned (light, for contrast)"))
    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
