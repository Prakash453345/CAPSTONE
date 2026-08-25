"""M4's own required ablation [build guide §7: "with and without the
theta_m blocking term, under a downstream bottleneck -- the blocking
term should show a large win here and roughly nothing in free flow"].

The previous chunk's finding (PROGRESS.md's M4 section) already showed
that raising demand alone -- even to 2x medium ("heavy") -- never pushes
any of the corridor's 7 junctions' own receiving lanes to real spillback:
congestion happens elsewhere on the network first. So this script
engineers a bottleneck on purpose rather than hoping demand finds one:
it picks the single busiest measured movement under heavy demand
(`measure_flows.compute_link_flows` against `vijayawada_corridor_heavy.rou.xml`),
finds the real lane that movement's traffic discharges into
(`link_lanes.link_to_receiving_lane_map`), and throttles every lane on
that receiving edge to a crawl via `run_controlled_scenario`'s new
`bottleneck_lane_speeds_mps` parameter (all lanes on the edge, not just
the one linked lane, so SUMO can't just lane-change traffic around a
single slow lane on an otherwise-normal edge).

Four runs, same seed and heavy demand throughout, only two things varied
(2x2): CA-MP with the blocking term on vs. off (`CampConfig.enable_blocking`),
and the bottleneck present vs. absent. Compared per arm: person-delay
(`control/metrics.compute_run_metrics`) and a spillback-episode count
scoped to *just* the bottleneck's own lanes (a `SpillbackTracker` over
those lanes only, not the whole corridor) -- a direct, already-built
measurement of "how bad did congestion get right there," reused rather
than building new instrumentation for one experiment.

Not part of the pytest suite: shells out to four real SUMO processes.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
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

_BOTTLENECK_SPEED_MPS = 2.0  # ~7.2 km/h -- a real crawl, not a full deadlock
_SEED = 1
# A capped run length, not the scenario's own natural "run until every
# vehicle clears" length. First run at the full length found that
# blocking_off actually pushes one junction's own Tier-0 config past
# what the safety kernel can satisfy under this bottleneck: the interlock
# rejects every proposal for thousands of consecutive ticks (self-
# recovering each time -- see runner.py's `_recover_from_fault` -- but
# never resolving while the artificial bottleneck's demand keeps
# arriving), which would otherwise make this experiment run for a very
# long wall-clock time without adding information beyond "it stays
# rejected." Capping here is itself part of the ablation's honest
# finding, not a shortcut around it -- see PROGRESS.md's M4 section.
_MAX_STEPS = 3600


def _lanes_of_edge(net_path: Path, edge_id: str) -> list[str]:
    root = ET.parse(net_path).getroot()
    for edge_el in root.findall("edge"):
        if edge_el.get("id") == edge_id:
            return [lane_el.get("id") for lane_el in edge_el.findall("lane")]
    raise ValueError(f"edge {edge_id!r} not found in {net_path}")


def _busiest_movement(flows: dict[str, dict[str, float]]) -> tuple[str, str, float]:
    best: tuple[str, str, float] | None = None
    for tls_id, links in flows.items():
        for link_id, flow in links.items():
            if best is None or flow > best[2]:
                best = (tls_id, link_id, flow)
    assert best is not None
    return best


def _run_arm(
    *,
    label: str,
    configs,
    flows,
    link_lanes,
    receiving_lanes,
    vtype_pcu,
    sumocfg_path: Path,
    tripinfo_path: Path,
    route_path: Path,
    enable_blocking: bool,
    bottleneck_lanes: list[str] | None,
) -> dict:
    per_junction_strategy = {}
    for tls_id, cfg in configs.items():
        timing = webster.compute_timing(cfg, flows.get(tls_id, {}))
        camp_cfg = camp.CampConfig(enable_blocking=enable_blocking)
        per_junction_strategy[tls_id] = partial(
            camp.propose, camp_cfg=camp_cfg, nominal_cycle_s=timing.cycle_s
        )

    bottleneck_speeds = (
        {lane_id: _BOTTLENECK_SPEED_MPS for lane_id in bottleneck_lanes}
        if bottleneck_lanes
        else None
    )

    print(f"\n--- running arm: {label} ---")
    result = run_controlled_scenario(
        str(sumocfg_path),
        configs,
        strategy=per_junction_strategy,
        seed=_SEED,
        link_lanes=link_lanes,
        receiving_lanes=receiving_lanes,
        vtype_pcu=vtype_pcu,
        tripinfo_output=str(tripinfo_path),
        spillback_lane_ids=bottleneck_lanes or [],
        bottleneck_lane_speeds_mps=bottleneck_speeds,
        max_steps=_MAX_STEPS,
    )
    run_metrics = metrics.compute_run_metrics(tripinfo_path, route_path)
    print(f"  steps={result['steps']} interlock_violations={result['interlock_violations']}")
    print(f"  bottleneck_spillback_episodes={result['spillback_events']}")
    print(f"  person_delay_s={run_metrics.person_delay_s:.1f}")
    print(f"  trips_completed={run_metrics.n_trips_total}")
    return {
        "label": label,
        "interlock_violations": result["interlock_violations"],
        "fault_events": result["fault_events"],
        "bottleneck_spillback_episodes": result["spillback_events"],
        "person_delay_s": run_metrics.person_delay_s,
        "trips_completed": run_metrics.n_trips_total,
    }


def main() -> None:
    net_path = _ROOT / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
    demand_dir = _ROOT / "scenarios" / "demand" / "vijayawada"
    sumocfg_path = demand_dir / "vijayawada_corridor_heavy.sumocfg"
    route_path = demand_dir / "vijayawada_corridor_heavy.rou.xml"
    out_dir = _ROOT / "scripts" / "_m4_ablation_out"
    out_dir.mkdir(exist_ok=True)

    configs = load_configs(net_path)
    flows = compute_link_flows(net_path, route_path)
    link_lanes = link_to_lane_map(net_path)
    receiving_lanes = link_to_receiving_lane_map(net_path)
    vtype_pcu = load_vtype_pcu(route_path)

    tls_id, link_id, flow = _busiest_movement(flows)
    bottleneck_edge_lane = receiving_lanes[tls_id][link_id]
    bottleneck_edge = bottleneck_edge_lane.rsplit("_", 1)[0]
    bottleneck_lanes = _lanes_of_edge(net_path, bottleneck_edge)
    print(f"busiest heavy-demand movement: {tls_id} {link_id} ({flow:.0f} veh/h)")
    print(f"bottleneck edge: {bottleneck_edge}, lanes: {bottleneck_lanes}")

    arms = [
        ("blocking_on__bottleneck_on", True, bottleneck_lanes),
        ("blocking_off__bottleneck_on", False, bottleneck_lanes),
        ("blocking_on__bottleneck_off", True, None),
        ("blocking_off__bottleneck_off", False, None),
    ]

    results = []
    for label, enable_blocking, lanes in arms:
        results.append(
            _run_arm(
                label=label,
                configs=configs,
                flows=flows,
                link_lanes=link_lanes,
                receiving_lanes=receiving_lanes,
                vtype_pcu=vtype_pcu,
                sumocfg_path=sumocfg_path,
                tripinfo_path=out_dir / f"{label}.tripinfo.xml",
                route_path=route_path,
                enable_blocking=enable_blocking,
                bottleneck_lanes=lanes,
            )
        )

    print("\n=== M4 theta_m ablation summary ===")
    header = (
        f"{'arm':<32}{'delay_s':>12}{'trips_completed':>17}"
        f"{'bottleneck_spillback':>22}{'interlock_violations':>22}"
    )
    print(header)
    for r in results:
        print(
            f"{r['label']:<32}{r['person_delay_s']:>12.1f}{r['trips_completed']:>17}"
            f"{r['bottleneck_spillback_episodes']:>22}{r['interlock_violations']:>22}"
        )

    # The real finding (see PROGRESS.md's M4 section): disabling blocking
    # alone -- even with no engineered bottleneck -- destabilizes this
    # corridor's own structurally-tight junction under heavy demand,
    # producing thousands of interlock rejections in BOTH blocking_off
    # arms, not just the one with a bottleneck. So there is no
    # violation-free arm to assert as a baseline here; this script's job
    # is to produce the table, not to gate on it. Read the violation
    # counts and person_delay_s together with real caution: a run with
    # more incomplete (never-finished) trips can show a *lower* summed
    # person_delay_s purely because a stranded trip's real delay is never
    # recorded -- always check completion rate (n_trips recorded per
    # arm's own tripinfo file) before comparing delay totals across arms.
    for r in results:
        if r["interlock_violations"] > 0:
            print(f"NOTE: {r['label']} took the failsafe path {r['interlock_violations']} times.")
    print("\nDone -- see the table above; interpret alongside completion rate, not delay alone.")


if __name__ == "__main__":
    main()
