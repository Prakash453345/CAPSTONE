"""M4's own gate deliverable [build guide §7]: "CA-MP beats the tuned
fixed-time baseline on person-delay at 3 demand levels, with zero
interlock violations, and does not starve any approach (max-wait
bounded)."

Design mirrors `scripts/bench.py`'s M3 gate script deliberately -- same
paired-seed methodology (every controller sees the identical seed set per
demand level, so a seed's own demand randomness cancels out of the
comparison), same `bench_stats.confidence_interval_95` mean +/- 95% CI
report, same "write every raw per-seed result to JSON, not just the
aggregate" transparency. What's new here relative to bench.py: two
controllers instead of three (webster fixed-time -- the actual "tuned
fixed-time baseline" the gate names, not semi/coordinated-actuated -- vs.
CA-MP with blocking enabled, i.e. the real controller, not an ablation
arm), crossed with three demand levels (light/medium/heavy) instead of
one. The baseline is re-tuned per demand level (its own Webster timing
computed from that level's own measured flows), not one fixed timing
reused across levels -- a weaker, undertuned baseline would make CA-MP's
win less meaningful, not more.

Zero interlock violations already structurally implies no starvation:
I5 (`max_wait_not_exceeded`) is exactly the safety-kernel predicate that
would reject a proposal before any *movement* waits longer than its
junction's own `Tier0Config.max_wait_s` without being served -- a
violation would show up in the interlock_violations column already
tracked, and that IS the gate's real "no starvation" evidence.

This script also reports each arm's `wait_time_s` (p95/max) from
`control/metrics.py` for context, but -- caught during the first draft of
this script, worth stating plainly rather than quietly fixing -- that
figure is NOT the same quantity I5 bounds, and must never be compared
against a junction's `max_wait_s` directly. `metrics.py`'s own module
docstring says why: it's SUMO's tripinfo `waitingTime`, a *whole-trip*
aggregate (summed over every signal a vehicle crosses along its route),
not a single junction's per-movement "time since last served" clock. A
vehicle crossing all 7 signal-controlled junctions in this corridor can
easily accumulate more total waiting time than any one junction's
`max_wait_s` ceiling while every individual junction along the way
stayed perfectly within bound -- that's expected, not a fault. The first
draft of this script's gate-check section compared the two directly and
printed a false "EXCEEDS a ceiling" alarm at all 3 demand levels; fixed
below to report interlock_violations as the real starvation check and
the trip-level wait figures as context only.

Not part of the pytest suite: shells out to 2 controllers x 3 demand
levels x 10 seeds = 60 real SUMO processes. Meant to be run once per gate
check, not on every CI run.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

from itms_domain import JunctionContext, SignalPlan, Tier0Config
from sim_service.control import bench_stats, metrics
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
_RESULTS_PATH = Path(__file__).resolve().parent / "results" / "m4_gate_results.json"

# Same N as the M3 gate (`scripts/bench.py`) -- see that script's own
# docstring for why 10 (matches the build guide's own example N; small
# enough that bench_stats' t-table covers it exactly, df=9).
_SEEDS = list(range(1, 11))

# A generous runaway guard, NOT the tight cap `m4_bottleneck_ablation.py`
# needed. That script capped at 3600 steps because an *engineered*
# bottleneck deliberately pushed a junction past what it could safely
# clear, so the run would never end on its own. Nothing here is
# artificially throttled -- the prior chunk's smoke test already showed
# all 3 demand levels finish cleanly in 2300-3200 steps under CA-MP with
# zero violations -- so this cap exists only to stop a genuinely stuck
# run from consuming unbounded wall-clock time, not to shape the result.
_MAX_STEPS_SAFETY_CAP = 6000

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


def _build_webster(configs: Mapping[str, Tier0Config], flows):
    timings = {
        tls_id: webster.compute_timing(cfg, flows.get(tls_id, {}))
        for tls_id, cfg in configs.items()
    }
    strategy = {tls_id: partial(webster.propose, timing=timings[tls_id]) for tls_id in configs}
    return strategy


def _build_camp(configs: Mapping[str, Tier0Config], flows):
    strategy: dict[str, Callable[[Tier0Config, JunctionContext], SignalPlan]] = {}
    for tls_id, cfg in configs.items():
        timing = webster.compute_timing(cfg, flows.get(tls_id, {}))
        # blocking always ON: this is the real controller, not the
        # ablation's disabled arm -- `m4_bottleneck_ablation.py` already
        # answered "does the blocking term matter"; this script answers
        # "does the real controller beat the baseline."
        camp_cfg = camp.CampConfig(enable_blocking=True)
        strategy[tls_id] = partial(camp.propose, camp_cfg=camp_cfg, nominal_cycle_s=timing.cycle_s)
    return strategy


_CONTROLLERS: dict[str, Callable] = {
    "webster": _build_webster,
    "camp": _build_camp,
}


def _run_one(
    controller: str,
    demand_level: str,
    seed: int,
    configs: Mapping[str, Tier0Config],
    flows: Mapping[str, Mapping[str, float]],
    vtype_pcu: Mapping[str, float],
    sumocfg_path: Path,
    route_path: Path,
    tripinfo_dir: Path,
) -> dict:
    strategy = _CONTROLLERS[controller](configs, flows)
    tripinfo_path = tripinfo_dir / f"{controller}_{demand_level}_seed{seed}.xml"
    kwargs: dict = dict(
        strategy=strategy,
        seed=seed,
        link_lanes=_link_lanes,
        tripinfo_output=str(tripinfo_path),
        max_steps=_MAX_STEPS_SAFETY_CAP,
    )
    if controller == "camp":
        kwargs["receiving_lanes"] = _receiving_lanes
        kwargs["vtype_pcu"] = vtype_pcu
    result = run_controlled_scenario(str(sumocfg_path), configs, **kwargs)
    run_metrics = metrics.compute_run_metrics(tripinfo_path, route_path)
    return {
        "steps": result["steps"],
        "interlock_violations": result["interlock_violations"],
        "fault_events": result["fault_events"],
        "n_trips_total": run_metrics.n_trips_total,
        "n_trips_scored": run_metrics.n_trips_scored,
        "person_delay_s": run_metrics.person_delay_s,
        "person_throughput_per_hour": run_metrics.person_throughput_per_hour,
        "wait_time_s": {
            "mean_s": run_metrics.wait_time_s.mean_s,
            "p50_s": run_metrics.wait_time_s.p50_s,
            "p95_s": run_metrics.wait_time_s.p95_s,
            "p99_s": run_metrics.wait_time_s.p99_s,
            "max_s": run_metrics.wait_time_s.max_s,
        },
        "stops_per_vehicle": run_metrics.stops_per_vehicle,
    }


def _print_table(demand_level: str, runs_by_controller: dict[str, list[dict]]) -> None:
    print(f"\n=== {demand_level} demand ===")
    header = (
        f"{'controller':<12} {'person-delay (p-s)':<24} {'throughput (p/h)':<22} "
        f"{'max-wait p95 (s)':<20} {'stops/veh':<16} {'trips completed':<16} {'violations':<10}"
    )
    print(header)
    print("-" * len(header))
    for controller, runs in runs_by_controller.items():
        delay_ci = bench_stats.confidence_interval_95([r["person_delay_s"] for r in runs])
        throughput_ci = bench_stats.confidence_interval_95(
            [r["person_throughput_per_hour"] for r in runs]
        )
        wait_p95_ci = bench_stats.confidence_interval_95(
            [r["wait_time_s"]["p95_s"] for r in runs]
        )
        stops_ci = bench_stats.confidence_interval_95([r["stops_per_vehicle"] for r in runs])
        total_violations = sum(r["interlock_violations"] for r in runs)
        completed = [r["n_trips_total"] for r in runs]
        print(
            f"{controller:<12} {str(delay_ci):<24} {str(throughput_ci):<22} "
            f"{str(wait_p95_ci):<20} {str(stops_ci):<16} "
            f"{f'{min(completed)}-{max(completed)}':<16} {total_violations:<10}"
        )


def main() -> None:
    configs = load_configs(_NET_PATH)
    max_wait_ceilings = {tls_id: cfg.max_wait_s for tls_id, cfg in configs.items()}
    print(f"loaded {len(configs)} junction configs; seeds={_SEEDS}")
    print(f"per-junction max_wait_s ceilings (I5's own bound): {max_wait_ceilings}")

    all_results: dict[str, dict[str, list[dict]]] = {
        level: {c: [] for c in _CONTROLLERS} for level in _DEMAND_LEVELS
    }
    raw_results: dict[str, dict[str, dict[int, dict]]] = {
        level: {c: {} for c in _CONTROLLERS} for level in _DEMAND_LEVELS
    }

    with tempfile.TemporaryDirectory(prefix="itms_m4_gate_") as tmp_dir:
        tripinfo_dir = Path(tmp_dir)
        for level, paths in _DEMAND_LEVELS.items():
            flows = compute_link_flows(_NET_PATH, paths["route"])
            vtype_pcu = load_vtype_pcu(paths["route"])
            for controller in _CONTROLLERS:
                for seed in _SEEDS:
                    run = _run_one(
                        controller,
                        level,
                        seed,
                        configs,
                        flows,
                        vtype_pcu,
                        paths["sumocfg"],
                        paths["route"],
                        tripinfo_dir,
                    )
                    all_results[level][controller].append(run)
                    raw_results[level][controller][seed] = run
                    print(
                        f"  {level}/{controller} seed={seed}: done "
                        f"(steps={run['steps']} violations={run['interlock_violations']} "
                        f"trips={run['n_trips_total']} delay_s={run['person_delay_s']:.1f})"
                    )
                    # Write after every run, not just at the end -- 60 runs
                    # is long enough that a crash partway through shouldn't
                    # cost every result already computed.
                    _RESULTS_PATH.write_text(
                        json.dumps(
                            {"seeds": _SEEDS, "max_wait_ceilings": max_wait_ceilings,
                             "results": raw_results},
                            indent=2,
                        )
                    )

    print(f"\nraw per-seed results written to {_RESULTS_PATH}\n")
    for level in _DEMAND_LEVELS:
        _print_table(level, all_results[level])

    print("\n=== gate check [build guide §7 M4] ===")
    for level in _DEMAND_LEVELS:
        webster_runs = all_results[level]["webster"]
        camp_runs = all_results[level]["camp"]
        webster_delay = [r["person_delay_s"] for r in webster_runs]
        camp_delay = [r["person_delay_s"] for r in camp_runs]
        webster_mean = sum(webster_delay) / len(webster_delay)
        camp_mean = sum(camp_delay) / len(camp_delay)
        total_violations = sum(r["interlock_violations"] for r in webster_runs + camp_runs)
        max_wait_seen = max(r["wait_time_s"]["max_s"] for r in webster_runs + camp_runs)
        beats = camp_mean < webster_mean
        verdict = "CA-MP wins" if beats else "CA-MP does NOT win"
        print(
            f"{level}: CA-MP mean delay {camp_mean:.1f} p-s vs webster {webster_mean:.1f} p-s "
            f"-> {verdict} on raw mean (always cross-check completion counts above)"
        )
        no_starve = (
            "no starvation (I5 never fired)" if total_violations == 0 else "STARVATION -- I5 fired"
        )
        print(
            f"   interlock_violations total (both controllers, {len(_SEEDS) * 2} runs): "
            f"{total_violations} -> {no_starve}"
        )
        print(
            f"   trip-level waiting-time (context only, NOT comparable to a junction's own "
            f"max_wait_s -- see module docstring): max observed {max_wait_seen:.1f}s"
        )


if __name__ == "__main__":
    main()
