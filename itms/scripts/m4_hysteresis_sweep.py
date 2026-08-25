"""Exploratory follow-up to the M4 gate comparison (`m4_gate_comparison.py`),
not a gate deliverable itself.

That comparison found CA-MP losing to tuned Webster on person-delay at
light/medium demand (~2x worse at both), tying only at heavy demand. The
`stops_per_vehicle` pattern in those results (CA-MP higher than Webster at
light/medium, lower at heavy) pointed at one candidate explanation: at
light/medium demand, no candidate phase's pressure clearly dominates, so
`camp.propose`'s own extend test --

    pressures[current] >= best_pressure - hysteresis_frac * abs(best_pressure)

-- rarely fails, and CA-MP tends to ride each phase out toward its own
`max_green_s` rather than cycling as briskly as Webster's short, already-
tuned fixed cycle. `hysteresis_frac` (`CampConfig`, default 0.05, exactly
§3.9's tabulated "5% of max P") controls the width of that tolerance band:
smaller means CA-MP gives up an extend sooner (switches more eagerly the
moment another phase's pressure edges ahead), larger means it holds on
longer. This script sweeps it in both directions to see which way actually
helps, rather than assuming the direction and tuning until the number
looks good.

Deliberately narrow scope for a first pass: only CA-MP is re-run (Webster
is untouched by this parameter, so its already-collected M4 gate numbers
are reused as the fixed comparison point); only light and medium demand
(where the earlier gap was largest -- heavy already ties); only 5 seeds
per value (not the gate's full 10) to triage cheaply before committing to
a fuller confirmation run on whichever value looks best. If a value here
looks like a real win, a full 10-seed run of just that value (matching
`m4_gate_comparison.py`'s own seed set for a fair before/after comparison)
is the natural next step, not folded into this script.

Not part of the pytest suite: shells out to real SUMO processes.
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

from sim_service.control import metrics
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

# A cheap triage set, not the gate's full 10 -- see module docstring.
_SEEDS = [1, 2, 3, 4, 5]

# The spec's own default (0.05) sits in the middle. 0.0 removes the
# tolerance band entirely (extend only if current is the literal max --
# the most eager-to-switch setting possible short of breaking the
# min_green hard floor, which stays enforced regardless). 0.15 tests the
# opposite direction, in case the real fix is "hold on longer, not
# shorter" -- this is an empirical question, not assumed.
_HYSTERESIS_VALUES = [0.0, 0.05, 0.15]

_DEMAND_LEVELS: dict[str, dict[str, Path]] = {
    "light": {
        "sumocfg": _DEMAND_DIR / "vijayawada_corridor_light.sumocfg",
        "route": _DEMAND_DIR / "vijayawada_corridor_light.rou.xml",
    },
    "medium": {
        "sumocfg": _DEMAND_DIR / "vijayawada_corridor.sumocfg",
        "route": _DEMAND_DIR / "vijayawada_corridor.rou.xml",
    },
}

# The M4 gate comparison's own already-collected Webster means (10 seeds
# each) -- reused as the fixed reference line on the printed table rather
# than re-running Webster here, since hysteresis_frac cannot affect it.
_WEBSTER_DELAY_S = {"light": 69541.4, "medium": 183547.0}

_link_lanes = link_to_lane_map(_NET_PATH)
_receiving_lanes = link_to_receiving_lane_map(_NET_PATH)


def _run_one(
    hysteresis_frac, level, seed, configs, flows, vtype_pcu,
    sumocfg_path, route_path, tripinfo_dir,
):
    strategy = {}
    for tls_id, cfg in configs.items():
        timing = webster.compute_timing(cfg, flows.get(tls_id, {}))
        camp_cfg = camp.CampConfig(enable_blocking=True, hysteresis_frac=hysteresis_frac)
        strategy[tls_id] = partial(camp.propose, camp_cfg=camp_cfg, nominal_cycle_s=timing.cycle_s)

    tripinfo_path = tripinfo_dir / f"h{hysteresis_frac}_{level}_seed{seed}.xml"
    result = run_controlled_scenario(
        str(sumocfg_path),
        configs,
        strategy=strategy,
        seed=seed,
        link_lanes=_link_lanes,
        receiving_lanes=_receiving_lanes,
        vtype_pcu=vtype_pcu,
        tripinfo_output=str(tripinfo_path),
    )
    run_metrics = metrics.compute_run_metrics(tripinfo_path, route_path)
    return {
        "interlock_violations": result["interlock_violations"],
        "n_trips_total": run_metrics.n_trips_total,
        "person_delay_s": run_metrics.person_delay_s,
        "stops_per_vehicle": run_metrics.stops_per_vehicle,
    }


def main() -> None:
    import tempfile

    configs = load_configs(_NET_PATH)
    print(f"loaded {len(configs)} junction configs; seeds={_SEEDS}; "
          f"hysteresis_frac values={_HYSTERESIS_VALUES}")

    with tempfile.TemporaryDirectory(prefix="itms_m4_hyst_") as tmp_dir:
        tripinfo_dir = Path(tmp_dir)
        results: dict[str, dict[float, list[dict]]] = {
            level: {h: [] for h in _HYSTERESIS_VALUES} for level in _DEMAND_LEVELS
        }
        for level, paths in _DEMAND_LEVELS.items():
            flows = compute_link_flows(_NET_PATH, paths["route"])
            vtype_pcu = load_vtype_pcu(paths["route"])
            for h in _HYSTERESIS_VALUES:
                for seed in _SEEDS:
                    run = _run_one(
                        h, level, seed, configs, flows, vtype_pcu,
                        paths["sumocfg"], paths["route"], tripinfo_dir,
                    )
                    results[level][h].append(run)
                    print(
                        f"  {level} h={h} seed={seed}: violations={run['interlock_violations']} "
                        f"trips={run['n_trips_total']} delay_s={run['person_delay_s']:.1f} "
                        f"stops/veh={run['stops_per_vehicle']:.2f}"
                    )

    print("\n=== hysteresis_frac sweep summary (5-seed triage, not the 10-seed gate) ===")
    for level in _DEMAND_LEVELS:
        print(f"\n{level} demand -- webster reference (10-seed gate mean): "
              f"{_WEBSTER_DELAY_S[level]:.1f} person-s")
        for h in _HYSTERESIS_VALUES:
            runs = results[level][h]
            mean_delay = sum(r["person_delay_s"] for r in runs) / len(runs)
            mean_stops = sum(r["stops_per_vehicle"] for r in runs) / len(runs)
            total_violations = sum(r["interlock_violations"] for r in runs)
            gap_pct = (mean_delay / _WEBSTER_DELAY_S[level] - 1.0) * 100
            print(
                f"  hysteresis_frac={h:<5} mean delay={mean_delay:>10.1f} p-s "
                f"({gap_pct:+.0f}% vs webster)  mean stops/veh={mean_stops:.2f}  "
                f"violations={total_violations}"
            )

    print(
        "\nNOTE: this is a 5-seed triage against a 10-seed webster reference -- "
        "enough to see direction and rough magnitude, not a gate-grade result. "
        "If one value clearly closes the gap, re-run it at the full 10 seeds "
        "(matching m4_gate_comparison.py's own seed set) before calling it settled."
    )


if __name__ == "__main__":
    main()
