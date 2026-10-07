"""Shared plumbing for the M8 (vision) experiments -- the counterpart of
`m5_harness.py`, which it builds on rather than duplicates.

Everything that is the same across the M8 gates lives here: loading the
committed camera registry, building the rig once per worker process, the
CC-A-CAMP arm exactly as `m5_baseline_benchmark.py` runs it (ceiling on,
supervisor on), and one `run_scenario` that accepts an `on_tick` hook -- the
one thing `m5_harness.run_one` deliberately does not know about.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from functools import cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from itms_geo import RoadNetwork  # noqa: E402
from m5_ccacamp_gate import _ARMS, CEILING_FACTOR  # noqa: E402
from m5_cycle_ceiling_probe import configs_with_ceiling  # noqa: E402
from sim_service.control import metrics  # noqa: E402
from sim_service.control.runner import run_controlled_scenario  # noqa: E402
from sim_service.control.strategies import hol, webster  # noqa: E402
from sim_service.control.strategies.hol_camp import HolAwareCamp, HolConfig  # noqa: E402
from vision_service.cameras import CameraRig, load_registry  # noqa: E402
from vision_service.classes import ClassTable  # noqa: E402
from vision_service.pipeline import VisionSystem  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = (H.SCENARIO_DIR / H.SCENARIO.get("cameras_file", "cameras.json") if H.SCENARIO
            else ROOT / "scenarios" / "networks" / "vijayawada" / "cameras.json")
EVAL_SEEDS = H.EVAL_SEEDS
TRAIN_SEEDS = H.TRAIN_SEEDS


def previous_runs(out: str | Path, key: str) -> list[dict]:
    """`--resume`: the runs an earlier, interrupted invocation already wrote
    to `out` (under `key`), so only the missing ones are re-run. Each run is
    self-contained and seeded, so a resumed gate gives the same numbers."""
    p = Path(out)
    if not p.exists():
        return []
    return list(json.loads(p.read_text()).get(key, []))


@cache
def network() -> RoadNetwork:
    return RoadNetwork.from_sumo_net(H.NET_PATH)


@cache
def rig(box: bool = False) -> CameraRig:
    """`box`: the rig with a junction-overview camera per junction
    (`scenarios/build_scenario.py --add-box-cameras`), for a controller that
    needs to see into the junction."""
    path = REGISTRY
    if box:
        if not (H.SCENARIO and H.SCENARIO.get("box_cameras_file")):
            raise SystemExit("this scenario has no junction-overview cameras: run "
                             "scenarios/build_scenario.py --add-box-cameras --out <scenario>")
        path = H.SCENARIO_DIR / H.SCENARIO["box_cameras_file"]
    specs, raw = load_registry(path)
    return CameraRig.build(network(), specs,
                           max_resolution_m_per_px=raw.get("max_resolution_m_per_px", 0.6))


@cache
def link_maps():
    return network().link_lane_maps()


def vision_factory(preset: str, seed: int, fps: float, *, box: bool = False,
                   **kwargs) -> Callable[[ClassTable], VisionSystem]:
    approach, receiving = link_maps()

    def make(classes: ClassTable) -> VisionSystem:
        return VisionSystem(rig(box), approach, receiving, classes=classes, preset=preset,
                            seed=seed, fps=fps, lane_chains=H.lane_chains(), **kwargs)

    return make


def ccacamp_inputs(level: str):
    return configs_with_ceiling(H.scenario_inputs(level), CEILING_FACTOR)


# The head-of-line-aware controller (`strategies/hol_camp.py`): CC-A-CAMP's
# settings, plus pricing of blocked lanes ("hol:price") and split variants
# for blocked approaches ("hol").
HOL_ARMS = {"hol": HolConfig(), "hol:price": HolConfig(use_variants=False),
            "hol:p0": HolConfig(min_blocked_changes=0.0),
            # multi-lane approaches get variants too: for any blocked lane (the
            # first version), or only while the whole approach is stalled
            "hol:lane": HolConfig(single_lane_only=False, whole_approach=False),
            "hol:multi": HolConfig(single_lane_only=False),
            # no limit on the length of a visit that uses a variant; a longer one
            # ways out of a variant: back to the base phase whenever it would
            # release more; never while another phase waits. (`hol:idle` is the
            # default under the name the choice was made with.)
            "hol:press": HolConfig(exit_by_pressure=True),
            "hol:idle": HolConfig(),
            "hol:term": HolConfig(terminal=True),
            "hol:nobudget": HolConfig(family_budget=1e9),
            "hol:b3": HolConfig(family_budget=3.0),
            # development arms (TRAIN seeds): how much a variant must gain
            "hol:m0.5": HolConfig(variant_gain_margin=0.5),
            "hol:m1": HolConfig(variant_gain_margin=1.0),
            # ... and how long the blockage must have lasted (change intervals)
            "hol:p1": HolConfig(min_blocked_changes=1.0),
            "hol:p2": HolConfig(min_blocked_changes=2.0)}


@cache
def _internal_links():
    return hol.internal_links(H.NET_PATH)


@cache
def _pedestrian_links():
    return hol.pedestrian_links(H.NET_PATH)


def hol_inputs(level: str, single_lane_only: bool = True):
    """CC-A-CAMP's inputs with each junction's split variants added to its
    phases (not to its ring), and `{tls: {variant: base}}`."""
    configs, flows, pcu, paths = ccacamp_inputs(level)
    approach, _ = link_maps()
    out, base_of = {}, {}
    for tls, cfg in configs.items():
        out[tls], base_of[tls] = hol.with_split_variants(
            cfg, approach.get(tls, {}), single_lane_only=single_lane_only,
            pedestrian=_pedestrian_links().get(tls, ()))
        # what adding the variants broke, not what the network's own
        # configuration already had (two Berlin lights have a one-way
        # entry in their conflict table)
        problems = sorted(set(out[tls].validate()) - set(cfg.validate()))
        if problems:
            raise ValueError(f"{tls}: configuration with variants is invalid: {problems}")
    return (out, flows, pcu, paths), base_of


def build_hol(arm: str, inputs, base_of):
    configs, flows, _, _ = inputs
    approach, _ = link_maps()
    return {
        tls: HolAwareCamp(
            _ARMS["ccacamp"],
            lane_of=approach.get(tls, {}),
            base_of=base_of.get(tls, {}),
            hol=HOL_ARMS[arm],
            nominal_cycle_s=webster.compute_timing(cfg, flows.get(tls, {})).cycle_s,
        )
        for tls, cfg in configs.items()
    }


def build_strategy(controller: str, inputs):
    configs, flows, _, _ = inputs
    if controller == "webster":
        return H.build_webster(configs, flows)
    if controller in _ARMS:
        return H.build_acamp(configs, flows, acamp_cfg=_ARMS[controller])
    raise ValueError(controller)


def run_scenario(
    controller: str,
    level: str,
    seed: int,
    *,
    strategy=None,
    inputs=None,
    on_tick=None,
    max_steps: int | None = None,
    incident_injector=None,
    tripinfo_dir: Path = Path("/tmp/m8_tripinfo"),
    tag: str = "",
    runner_kwargs: dict | None = None,
) -> dict:
    """One scenario, scored with the project's own metrics (person delay,
    stops, throughput, waits), plus the runner's interlock count.
    `runner_kwargs` go straight to `run_controlled_scenario` (for instance
    M6's `anomaly_graph` and `anomaly_feature_sink`)."""
    if controller in HOL_ARMS:
        arm = HOL_ARMS[controller]
        inputs, base_of = hol_inputs(level, arm.single_lane_only)
        strategy = build_hol(controller, inputs, base_of)
        runner_kwargs = {**(runner_kwargs or {}), "internal_links": _internal_links()}
    if inputs is None:
        inputs = ccacamp_inputs(level) if controller != "webster" else H.scenario_inputs(level)
    configs, flows, vtype_pcu, paths = inputs
    if strategy is None:
        strategy = build_strategy(controller, inputs)
    approach, receiving = link_maps()
    tripinfo_dir.mkdir(parents=True, exist_ok=True)
    # no ':' in the name: SUMO reads "a:b" as a socket (host:port)
    trip = tripinfo_dir / (f"{controller}_{tag}_{level}_seed{seed}_{time.time_ns()}.xml"
                           .replace(":", "_"))
    kwargs: dict = dict(
        strategy=strategy,
        seed=seed,
        link_lanes=approach,
        tripinfo_output=str(trip),
        max_steps=max_steps or H.MAX_STEPS_SAFETY_CAP,
        on_tick=on_tick,
    )
    if controller != "webster":
        kwargs["receiving_lanes"] = receiving
        kwargs["vtype_pcu"] = vtype_pcu
        if H.lane_chains() is not None:
            kwargs["lane_chains"] = H.lane_chains()
    if incident_injector is not None:
        kwargs["incident_injector"] = incident_injector
    kwargs.update(runner_kwargs or {})
    t0 = time.time()
    result = run_controlled_scenario(str(paths["sumocfg"]), configs, **kwargs)
    m = metrics.compute_run_metrics(trip, paths["route"])
    rec = {
        "scenario": H.SCENARIO_NAME,
        "lane_chains": H.lane_chains() is not None and controller != "webster",
        "controller": controller,
        "demand_level": level,
        "seed": seed,
        "steps": result["steps"],
        "interlock_violations": result["interlock_violations"],
        "teleports": result.get("teleports"),
        "longest_wait_excess_s": result.get("longest_wait_excess_s"),
        "waits_over_bound": result.get("waits_over_bound"),
        "unfinished_at_cap": result.get("unfinished_at_cap"),
        "person_delay_s": m.person_delay_s,
        "person_throughput_per_hour": m.person_throughput_per_hour,
        "stops_per_vehicle": m.stops_per_vehicle,
        "wait_time_s": {"mean_s": m.wait_time_s.mean_s, "p95_s": m.wait_time_s.p95_s,
                        "max_s": m.wait_time_s.max_s},
        "wall_s": round(time.time() - t0, 1),
    }
    if controller != "webster" and isinstance(strategy, dict):
        totals: dict[str, int] = {}
        for ctrl in strategy.values():
            for k, v in getattr(ctrl, "stats", {}).items():
                totals[k] = totals.get(k, 0) + v
        rec["decision_stats"] = totals
    trip.unlink(missing_ok=True)
    return rec
