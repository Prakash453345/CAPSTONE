"""The M3 gate deliverable itself [build guide §7 M3 / §8.2]: run the three
tuned baseline controllers -- Webster fixed-time, semi-actuated,
coordinated-actuated -- over the same 10 seeds each (a *paired* design:
every controller sees the identical seed set, so a seed's own demand
randomness cancels out of the comparison instead of adding noise to it),
score every run with the M3 metrics collector (`control/metrics.py`), and
report mean ± 95% CI per controller for person-delay, person-throughput,
max-wait, and stops -- the exact table `make bench` promises.

Deliberately excludes M2's untuned fixed-time strategy: the gate's own
wording is "three baseline controllers," and re-reading the build guide
[§7] confirms those three are Webster/semi-actuated/coordinated-actuated,
not the naive floor-clamped ring M2 built before any tuning existed. The
untuned baseline's numbers are already recorded as a single-seed,
honestly-labelled comparison point in `PROGRESS.md`'s M3 section, not
folded into this statistical table.

`_SEEDS` is the fixed workload manifest [§8.2: "check the seeds into the
repo"] -- 10 seeds, matching the gate's own N. Raw per-seed results are
also written to `bench_results.json` alongside this script, so every
number in the printed table traces back to an individual run rather than
only existing as an aggregate.

Not part of the pytest suite for the same reason every other M3 smoke
script isn't: it shells out to 30 real SUMO processes (3 controllers x 10
seeds). Takes on the order of a few minutes, not milliseconds.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

import traci
from itms_domain import JunctionContext, SignalPlan, Tier0Config
from sim_service.control import bench_stats, metrics
from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies import coordinated_actuated as ca
from sim_service.control.strategies import semi_actuated, webster

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scenarios" / "networks" / "vijayawada"))
from corridor_geometry import cumulative_distances_m  # noqa: E402
from extract_tier0_config import load_configs  # noqa: E402
from link_lanes import link_to_lane_map  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402

_NET_PATH = _ROOT / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
_SUMOCFG_PATH = _ROOT / "scenarios" / "demand" / "vijayawada" / "vijayawada_corridor.sumocfg"
_ROUTE_PATH = _ROOT / "scenarios" / "demand" / "vijayawada" / "vijayawada_corridor.rou.xml"
_RESULTS_PATH = Path(__file__).resolve().parent / "bench_results.json"

# The fixed workload manifest [§8.2] -- 10 seeds, the same set for every
# controller (paired comparisons), checked into the repo via this file.
_SEEDS = list(range(1, 11))

_StrategyBuilder = Callable[
    [Mapping[str, Tier0Config], Mapping[str, Mapping[str, float]]],
    tuple[Mapping[str, Callable[[Tier0Config, JunctionContext], SignalPlan]],
          Mapping[str, Mapping[str, str]] | None],
]


def _build_webster(configs, flows):
    timings = {
        tls_id: webster.compute_timing(cfg, flows.get(tls_id, {}))
        for tls_id, cfg in configs.items()
    }
    strategy = {
        tls_id: partial(webster.propose, timing=timings[tls_id]) for tls_id in configs
    }
    return strategy, None


def _build_semi_actuated(configs, flows):
    link_lanes = link_to_lane_map(_NET_PATH)
    major_phases = {}
    for tls_id, cfg in configs.items():
        timing = webster.compute_timing(cfg, flows.get(tls_id, {}))
        major_phases[tls_id] = semi_actuated.pick_major_phase(timing.critical_flow_ratios)
    strategy = {
        tls_id: partial(semi_actuated.propose, major_phase_id=major_phases[tls_id])
        for tls_id in configs
    }
    return strategy, link_lanes


def _build_coordinated_actuated(configs, flows):
    link_lanes = link_to_lane_map(_NET_PATH)
    distances_m = cumulative_distances_m(_NET_PATH)
    plans = ca.build_corridor_plan(configs, flows, distances_m)

    def make_strategy(coordination: ca.CoordinationPlan):
        def strategy(cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan:
            return ca.propose(
                cfg, ctx, coordination=coordination, system_time_s=traci.simulation.getTime()
            )

        return strategy

    strategy = {tls_id: make_strategy(plans[tls_id]) for tls_id in configs}
    return strategy, link_lanes


_CONTROLLERS: dict[str, _StrategyBuilder] = {
    "webster": _build_webster,
    "semi_actuated": _build_semi_actuated,
    "coordinated_actuated": _build_coordinated_actuated,
}


def _run_one(
    controller: str,
    seed: int,
    configs: Mapping[str, Tier0Config],
    flows: Mapping[str, Mapping[str, float]],
    tripinfo_dir: Path,
) -> metrics.RunMetrics:
    strategy, link_lanes = _CONTROLLERS[controller](configs, flows)
    tripinfo_path = tripinfo_dir / f"{controller}_seed{seed}.xml"
    result = run_controlled_scenario(
        str(_SUMOCFG_PATH),
        configs,
        strategy=strategy,
        seed=seed,
        link_lanes=link_lanes,
        tripinfo_output=str(tripinfo_path),
    )
    if result["interlock_violations"] != 0 or result["fault_events"]:
        raise SystemExit(
            f"FAIL: {controller} seed={seed} was not safe -- "
            f"{result['interlock_violations']} interlock violations, "
            f"fault_events={result['fault_events']}. A bench run over an unsafe "
            f"controller invalidates every number in the table (build guide §8.1: "
            f"interlock violations must be exactly zero, always)."
        )
    return metrics.compute_run_metrics(tripinfo_path, _ROUTE_PATH)


def _print_table(all_metrics: dict[str, list[metrics.RunMetrics]]) -> None:
    header = f"{'controller':<22} {'person-delay (p-s)':<24} {'throughput (p/h)':<22} " \
             f"{'max-wait p95 (s)':<20} {'stops/veh':<16}"
    print(header)
    print("-" * len(header))
    for controller, runs in all_metrics.items():
        delay_ci = bench_stats.confidence_interval_95([r.person_delay_s for r in runs])
        throughput_ci = bench_stats.confidence_interval_95(
            [r.person_throughput_per_hour for r in runs]
        )
        wait_p95_ci = bench_stats.confidence_interval_95([r.wait_time_s.p95_s for r in runs])
        stops_ci = bench_stats.confidence_interval_95([r.stops_per_vehicle for r in runs])
        print(
            f"{controller:<22} {str(delay_ci):<24} {str(throughput_ci):<22} "
            f"{str(wait_p95_ci):<20} {str(stops_ci):<16}"
        )


def main() -> None:
    configs = load_configs(_NET_PATH)
    flows = compute_link_flows()
    print(f"loaded {len(configs)} junction configs; seeds={_SEEDS}")

    all_metrics: dict[str, list[metrics.RunMetrics]] = {name: [] for name in _CONTROLLERS}
    raw_results: dict[str, dict[int, dict]] = {name: {} for name in _CONTROLLERS}

    with tempfile.TemporaryDirectory(prefix="itms_bench_") as tmp_dir:
        tripinfo_dir = Path(tmp_dir)
        for controller in _CONTROLLERS:
            for seed in _SEEDS:
                run_metrics = _run_one(controller, seed, configs, flows, tripinfo_dir)
                all_metrics[controller].append(run_metrics)
                raw_results[controller][seed] = {
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
                print(
                    f"  {controller} seed={seed}: done "
                    f"({run_metrics.n_trips_scored} scored trips)"
                )

    _RESULTS_PATH.write_text(json.dumps({"seeds": _SEEDS, "results": raw_results}, indent=2))
    print(f"\nraw per-seed results written to {_RESULTS_PATH}\n")
    _print_table(all_metrics)


if __name__ == "__main__":
    main()
