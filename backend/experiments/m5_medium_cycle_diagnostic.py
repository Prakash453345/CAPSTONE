"""What is actually costing A-CA-MP 25% at medium demand?

The ablation ruled out the obvious suspect (`protect_allocated_green`
now firing at medium after the cabinet fix -- turning it off did not
help). This follows the signature instead of the mechanism.

**The signature.** At medium, post-cabinet-fix, over the same 10 seeds:

    person-delay       Webster 193,354   A-CA-MP 243,015   (+25.7%)
    stops per vehicle  Webster    3.09   A-CA-MP    2.78   (-10.0%)

A-CA-MP stops vehicles **less often** and delays them **more**. That
combination is not ambiguous. Being stopped fewer times while waiting
longer in total means the waits are longer *per stop* -- vehicles sitting
through one long red rather than being released and re-stopped. Short
cycles produce the opposite signature: more stops, less delay each.

So the suspect is **cycle length**, not switching logic. Webster's whole
method is a closed-form optimum cycle computed from measured flows; A-CA-MP
has no cycle concept at all -- its effective cycle is whatever emerges from
tick-by-tick extend/switch decisions. Nothing in the controller constrains
that emergent cycle to be anywhere near the delay-minimising one.

This script measures both, with no simulation of its own: Webster's cycle
comes from `compute_timing` on the same measured flows the gate arm used,
and A-CA-MP's emergent cycle comes from the decision counters the gate
already recorded (ticks divided by phase changes, per junction).

If the two are close, this hypothesis is dead and the cost is elsewhere.
If A-CA-MP's emergent cycle is much longer, that is the explanation, and
it is also a *fixable* one -- an emergent quantity with no bound is the
kind of defect this project has found three times already.
"""

from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from sim_service.control.strategies import webster  # noqa: E402

_GATE = Path(__file__).resolve().parent / "m5_artifacts" / "m5_gate_medium_postfix.json"


def _paired(gate: dict, level: str, key: str = "person_delay_s") -> str:
    by: dict[str, dict[int, float]] = {}
    for r in gate["runs"]:
        if r["demand_level"] != level:
            continue
        by.setdefault(r["controller"], {})[r["seed"]] = r[key]
    if "webster" not in by or "acamp" not in by:
        return "  (both arms not present in this artefact)"
    seeds = sorted(set(by["webster"]) & set(by["acamp"]))
    diffs = [by["acamp"][s] - by["webster"][s] for s in seeds]
    mean = st.fmean(diffs)
    half = 2.262 * st.stdev(diffs) / len(diffs) ** 0.5
    base = st.fmean(by["webster"][s] for s in seeds)
    sig = (mean - half) * (mean + half) > 0
    return (
        f"  A-CA-MP vs Webster: {mean:+,.0f} ({100 * mean / base:+.1f}%)  "
        f"95% CI [{mean - half:+,.0f}, {mean + half:+,.0f}]  "
        f"{'SIGNIFICANT' if sig else 'not significant'}  "
        f"({sum(1 for d in diffs if d > 0)}/{len(diffs)} seeds worse)"
    )


def cycle_ratio(level: str, gate_path: Path) -> None:
    """Emergent cycle vs Webster's optimum, for one demand level."""
    configs, flows, _v, _p = H.scenario_inputs(level)
    wc = st.fmean(
        webster.compute_timing(cfg, flows.get(t, {})).cycle_s for t, cfg in configs.items()
    )
    gate = json.loads(gate_path.read_text())
    runs = [
        r for r in gate["runs"] if r["controller"] == "acamp" and r["demand_level"] == level
    ]
    if not runs:
        print(f"{level:7s} no acamp runs in {gate_path.name}")
        return
    n_j = len(configs)
    phases = st.fmean(len(c.ring_order) for c in configs.values())
    cycles = []
    for r in runs:
        s = r["decision_stats"]
        sw = (
            s.get("switch_pressure", 0)
            + s.get("switch_max_green", 0)
            + s.get("switch_starvation", 0)
        ) / n_j
        cycles.append(((s["ticks"] / n_j) / sw) * phases if sw else 0.0)
    mc = st.fmean(cycles)
    viol = sum(r["interlock_violations"] for r in runs)
    print(
        f"{level:7s}  Webster optimum {wc:5.1f}s   A-CA-MP emergent {mc:5.1f}s   "
        f"ratio {mc / wc:4.2f}x   (acamp interlock violations: {viol})"
    )
    print(_paired(gate, level))


def main() -> None:
    configs, flows, _vtype_pcu, _paths = H.scenario_inputs("medium")

    print("=== Webster's delay-minimising cycle, per junction (from measured flows) ===")
    cycles = {}
    for tls_id, cfg in configs.items():
        timing = webster.compute_timing(cfg, flows.get(tls_id, {}))
        cycle = getattr(timing, "cycle_s", None)
        greens = getattr(timing, "green_s", None) or {}
        cycles[tls_id] = cycle
        g = ", ".join(f"{p}={v:.0f}s" for p, v in sorted(greens.items()))
        print(f"  {tls_id[:34]:34s} cycle {cycle:6.1f}s   greens: {g}")
    finite = [c for c in cycles.values() if c]
    print(f"\n  Webster mean cycle: {st.fmean(finite):.1f}s "
          f"(min {min(finite):.1f}, max {max(finite):.1f})")

    if not _GATE.exists():
        print(f"\n{_GATE} not found -- run the medium gate first.")
        return

    gate = json.loads(_GATE.read_text())
    acamp_runs = [r for r in gate["runs"] if r["controller"] == "acamp"]
    n_junctions = len(configs)

    print(f"\n=== A-CA-MP's emergent cycle at medium ({len(acamp_runs)} seeds) ===")
    per_seed = []
    for r in acamp_runs:
        s = r["decision_stats"]
        # Counters are summed across junctions by the harness, so divide
        # both sides by the junction count rather than only one of them.
        ticks_per_junction = s["ticks"] / n_junctions
        switches = (
            s.get("switch_pressure", 0)
            + s.get("switch_max_green", 0)
            + s.get("switch_starvation", 0)
        )
        switches_per_junction = switches / n_junctions
        mean_green = ticks_per_junction / switches_per_junction if switches_per_junction else 0.0
        phases = st.fmean(len(c.ring_order) for c in configs.values())
        per_seed.append((mean_green, mean_green * phases))
        print(f"  seed {r['seed']:3d}  mean green {mean_green:5.1f}s  "
              f"=> cycle ~{mean_green * phases:5.1f}s  "
              f"({switches_per_junction:.0f} phase changes per junction)")

    mg = st.fmean(x for x, _ in per_seed)
    mc = st.fmean(y for _, y in per_seed)
    wc = st.fmean(finite)
    print(f"\n  A-CA-MP mean green {mg:.1f}s  =>  emergent cycle ~{mc:.1f}s")
    print(f"  Webster  cycle     {wc:.1f}s")
    print(f"\n  RATIO: A-CA-MP's cycle is {mc / wc:.2f}x Webster's optimum")

    print("\n  Webster's own delay curve is flat-bottomed but asymmetric: running")
    print("  well ABOVE the optimum cycle costs far more delay than running the")
    print("  same distance below it. A ratio meaningfully above 1 is therefore")
    print("  both an explanation and a direction.")

    print("\n=== The same ratio at every demand level ===\n")
    lh = _GATE.parent / "m5_gate_lightheavy_postfix.json"
    for level, path in (("light", lh), ("medium", _GATE), ("heavy", lh)):
        if path.exists():
            cycle_ratio(level, path)
            print()


if __name__ == "__main__":
    main()
