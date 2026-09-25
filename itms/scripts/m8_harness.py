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
from vision_service.cameras import CameraRig, load_registry  # noqa: E402
from vision_service.classes import ClassTable  # noqa: E402
from vision_service.pipeline import VisionSystem  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "scenarios" / "networks" / "vijayawada" / "cameras.json"
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
def rig() -> CameraRig:
    specs, raw = load_registry(REGISTRY)
    return CameraRig.build(network(), specs,
                           max_resolution_m_per_px=raw.get("max_resolution_m_per_px", 0.6))


@cache
def link_maps():
    return network().link_lane_maps()


def vision_factory(preset: str, seed: int, fps: float, **kwargs) -> Callable[[ClassTable],
                                                                              VisionSystem]:
    approach, receiving = link_maps()

    def make(classes: ClassTable) -> VisionSystem:
        return VisionSystem(rig(), approach, receiving, classes=classes, preset=preset,
                            seed=seed, fps=fps, **kwargs)

    return make


def ccacamp_inputs(level: str):
    return configs_with_ceiling(H.scenario_inputs(level), CEILING_FACTOR)


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
) -> dict:
    """One scenario, scored with the project's own metrics (person delay,
    stops, throughput, waits), plus the runner's interlock count."""
    if inputs is None:
        inputs = ccacamp_inputs(level) if controller != "webster" else H.scenario_inputs(level)
    configs, flows, vtype_pcu, paths = inputs
    if strategy is None:
        strategy = build_strategy(controller, inputs)
    approach, receiving = link_maps()
    tripinfo_dir.mkdir(parents=True, exist_ok=True)
    trip = tripinfo_dir / f"{controller}_{tag}_{level}_seed{seed}_{time.time_ns()}.xml"
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
    if incident_injector is not None:
        kwargs["incident_injector"] = incident_injector
    t0 = time.time()
    result = run_controlled_scenario(str(paths["sumocfg"]), configs, **kwargs)
    m = metrics.compute_run_metrics(trip, paths["route"])
    rec = {
        "controller": controller,
        "demand_level": level,
        "seed": seed,
        "steps": result["steps"],
        "interlock_violations": result["interlock_violations"],
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
