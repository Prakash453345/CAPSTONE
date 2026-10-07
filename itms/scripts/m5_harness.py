"""Shared scenario-running harness for M5's training and gate scripts.

Exists so that "run one scenario with controller X at demand level Y on
seed Z" has exactly one definition. `train_acamp.py` and
`m5_gate_comparison.py` must agree on it precisely -- a tuner optimizing
against a subtly different setup from the one the gate measures would
produce a number that means nothing -- and two hand-maintained copies of
a 40-line run function is how that divergence happens.

**Seed discipline, which is the methodological core of the whole
milestone.** `control/memory.py` argues that one SUMO seed is one "day"
at the junction: same time-of-day demand shape, different stochastic
realization. That analogy is what makes learning across runs legitimate,
and it carries an obligation -- anything the controller *learned from*
must be disjoint from what it is *evaluated on*, or the gate is testing
on its training set.

    TRAIN_SEEDS = 101..110   demand memory is built here; the parameter
                             search evaluates candidates here
    EVAL_SEEDS  = 1..10      the gate measures here, and nothing tuned or
                             remembered has ever seen these

`EVAL_SEEDS` is deliberately the same 1..10 the M4 gate used
(`scripts/m4_gate_comparison.py`), so M5's numbers sit in the same table
as M4's recorded ones rather than beside an incomparable set.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from functools import cache, partial
from pathlib import Path

from itms_domain import Tier0Config
from itms_domain.lane_chains import from_sumo_net as chains_from_net
from sim_service.control import metrics
from sim_service.control.memory import DemandMemory, LoadBaseline
from sim_service.control.online_calibration import OnlineCalibration
from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies import acamp, camp, webster
from sim_service.signal_controller.queue_state import load_vtype_pcu

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scenarios" / "networks" / "vijayawada"))
from extract_tier0_config import load_configs  # noqa: E402
from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402

# Which road network. The Vijayawada corridor unless `ITMS_SCENARIO` names a
# directory built by `scenarios/build_scenario.py` (any network, demand levels
# set by how loaded its busiest junction is). Read at import, so every worker
# process of a gate sees the same scenario as its parent.
SCENARIO_DIR = Path(os.environ["ITMS_SCENARIO"]).resolve() if os.environ.get("ITMS_SCENARIO") \
    else None
SCENARIO = json.loads((SCENARIO_DIR / "scenario.json").read_text()) if SCENARIO_DIR else None
SCENARIO_NAME = SCENARIO["name"] if SCENARIO else "vijayawada"

NET_PATH = _ROOT / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
DEMAND_DIR = _ROOT / "scenarios" / "demand" / "vijayawada"
ARTIFACT_DIR = Path(__file__).resolve().parent / "results" / "m5_artifacts"

TRAIN_SEEDS = list(range(101, 111))
EVAL_SEEDS = list(range(1, 11))

# Same generous runaway guard `m4_gate_comparison.py` uses, and for the
# same reason: not to shape the result, only to stop a genuinely stuck
# run from consuming unbounded wall-clock.
MAX_STEPS_SAFETY_CAP = 6000

DEMAND_LEVELS: dict[str, dict[str, Path]] = {
    "light": {
        "sumocfg": DEMAND_DIR / "vijayawada_corridor_light.sumocfg",
        "route": DEMAND_DIR / "vijayawada_corridor_light.rou.xml",
    },
    "medium": {
        "sumocfg": DEMAND_DIR / "vijayawada_corridor.sumocfg",
        "route": DEMAND_DIR / "vijayawada_corridor.rou.xml",
    },
    "heavy": {
        "sumocfg": DEMAND_DIR / "vijayawada_corridor_heavy.sumocfg",
        "route": DEMAND_DIR / "vijayawada_corridor_heavy.rou.xml",
    },
}


if SCENARIO is not None:
    NET_PATH = SCENARIO_DIR / SCENARIO["net"]
    DEMAND_DIR = SCENARIO_DIR
    DEMAND_LEVELS = {
        level: {"sumocfg": SCENARIO_DIR / v["sumocfg"], "route": SCENARIO_DIR / v["route"]}
        for level, v in SCENARIO["levels"].items()
    }


# `itms_domain.lane_chains`: measure a road SUMO split into several edges
# (a turn bay, an OpenStreetMap tag change) as the whole road. On by default;
# `ITMS_LANE_CHAINS=0` turns it off, for the with/without comparison only.
LANE_CHAINS_ON = os.environ.get("ITMS_LANE_CHAINS", "1") != "0"


@cache
def lane_chains() -> tuple[dict, dict] | None:
    """`(upstream, downstream)` for `NET_PATH`, or None when switched off or
    when the network has nothing to chain (the runner then does exactly
    what it did before chains existed)."""
    if not LANE_CHAINS_ON:
        return None
    up, down = chains_from_net(NET_PATH)
    return (up, down) if (up or down) else None


def scenario_inputs(demand_level: str):
    """Everything a run needs that depends only on the demand level, so
    the (slow, XML-parsing) load happens once per worker process rather
    than once per run."""
    paths = DEMAND_LEVELS[demand_level]
    configs = load_configs(NET_PATH)
    flows = compute_link_flows(NET_PATH, paths["route"])
    vtype_pcu = load_vtype_pcu(paths["route"])
    return configs, flows, vtype_pcu, paths


def build_webster(configs: Mapping[str, Tier0Config], flows, **_):
    return {
        tls_id: partial(webster.propose, timing=webster.compute_timing(cfg, flows.get(tls_id, {})))
        for tls_id, cfg in configs.items()
    }


def build_camp(configs: Mapping[str, Tier0Config], flows, **_):
    """M4's controller exactly as its own gate ran it -- blocking on, its
    own defaults, untouched. This arm exists to reproduce the recorded
    M4 result inside the same harness that measures M5, so any difference
    between the two is attributable to the controller and not to the
    harness."""
    strategy = {}
    for tls_id, cfg in configs.items():
        timing = webster.compute_timing(cfg, flows.get(tls_id, {}))
        strategy[tls_id] = partial(
            camp.propose,
            camp_cfg=camp.CampConfig(enable_blocking=True),
            nominal_cycle_s=timing.cycle_s,
        )
    return strategy


def build_acamp(
    configs: Mapping[str, Tier0Config],
    flows,
    *,
    acamp_cfg: acamp.AcampConfig | None = None,
    demand_memory: DemandMemory | None = None,
    calibration: OnlineCalibration | None = None,
    load_baseline: LoadBaseline | None = None,
    **_,
):
    """One `AdaptiveCamp` instance per junction -- stateful, so instances
    must not be shared between junctions or between runs. The same
    `DemandMemory` object *is* shared across junctions on purpose: it is
    the corridor's profile, keyed by junction internally. `load_baseline`
    follows the identical pattern for `AcampConfig.baseline_halflife_s`'s
    slow EWMA -- each junction's `AdaptiveCamp` is seeded from
    `load_baseline.get(tls_id)` (0.0, unchanged, when `load_baseline` is
    `None`) instead of always starting cold."""
    return {
        tls_id: acamp.AdaptiveCamp(
            acamp_cfg,
            nominal_cycle_s=webster.compute_timing(cfg, flows.get(tls_id, {})).cycle_s,
            demand_memory=demand_memory,
            calibration=calibration,
            initial_baseline_load=load_baseline.get(tls_id) if load_baseline is not None else 0.0,
        )
        for tls_id, cfg in configs.items()
    }


CONTROLLERS: dict[str, Callable] = {
    "webster": build_webster,
    "camp": build_camp,
    "acamp": build_acamp,
}

# Controllers needing the queue sampler wired (PCU queues, receiving-link
# state). Webster is demand-blind and needs none of it.
_NEEDS_QUEUE_STATE = frozenset({"camp", "acamp"})


def run_one(
    controller: str,
    demand_level: str,
    seed: int,
    *,
    tripinfo_dir: Path,
    acamp_cfg: acamp.AcampConfig | None = None,
    demand_memory: DemandMemory | None = None,
    calibration: OnlineCalibration | None = None,
    load_baseline: LoadBaseline | None = None,
    record_memory: bool = False,
    record_calibration: bool = True,
    record_baseline: bool = False,
    max_steps: int | None = None,
    inputs=None,
) -> dict:
    """One scenario. Returns the per-run scorecard the gate aggregates.

    `demand_memory` is passed to the *strategy* (so it can blend against
    history) and, only when `record_memory`, also to the runner (so this
    run's observations are folded into it). Those are deliberately
    separate switches: a training run records without blending, an
    evaluation run blends against a frozen profile without recording, and
    conflating them is how a gate result quietly becomes self-referential.

    `load_baseline` follows the same split, `record_baseline` playing
    `record_memory`'s role: every run reads it (to seed
    `AdaptiveCamp._baseline_load_ewma`), but only a warm-up run writes its
    ending value back -- an evaluation run must score a *frozen* baseline,
    the same reason `record_calibration` distinguishes reading a learned
    model from updating one.
    """
    configs, flows, vtype_pcu, paths = inputs or scenario_inputs(demand_level)
    link_lanes = link_to_lane_map(NET_PATH)
    receiving_lanes = link_to_receiving_lane_map(NET_PATH)

    strategy = CONTROLLERS[controller](
        configs,
        flows,
        acamp_cfg=acamp_cfg,
        demand_memory=demand_memory,
        calibration=calibration,
        load_baseline=load_baseline,
    )
    tripinfo_dir.mkdir(parents=True, exist_ok=True)
    tripinfo_path = tripinfo_dir / f"{controller}_{demand_level}_seed{seed}.xml"

    kwargs: dict = dict(
        strategy=strategy,
        seed=seed,
        link_lanes=link_lanes,
        tripinfo_output=str(tripinfo_path),
        max_steps=max_steps or MAX_STEPS_SAFETY_CAP,
    )
    if controller in _NEEDS_QUEUE_STATE:
        kwargs["receiving_lanes"] = receiving_lanes
        kwargs["vtype_pcu"] = vtype_pcu
        if lane_chains() is not None:
            kwargs["lane_chains"] = lane_chains()
    if record_memory and demand_memory is not None:
        kwargs["demand_memory"] = demand_memory
    if calibration is not None and record_calibration:
        # Separate switch from passing it to the strategy, for the same
        # reason `record_memory` is separate: an evaluation against a
        # *frozen* model must read it without writing to it, or the run
        # is scoring a model that has already seen the seed it is being
        # scored on.
        kwargs["calibration"] = calibration

    result = run_controlled_scenario(str(paths["sumocfg"]), configs, **kwargs)
    run_metrics = metrics.compute_run_metrics(tripinfo_path, paths["route"])

    record = {
        "controller": controller,
        "demand_level": demand_level,
        "seed": seed,
        "steps": result["steps"],
        "interlock_violations": result["interlock_violations"],
        "n_trips_total": run_metrics.n_trips_total,
        "n_trips_scored": run_metrics.n_trips_scored,
        "person_delay_s": run_metrics.person_delay_s,
        "person_throughput_per_hour": run_metrics.person_throughput_per_hour,
        "stops_per_vehicle": run_metrics.stops_per_vehicle,
        "wait_time_s": {
            "mean_s": run_metrics.wait_time_s.mean_s,
            "p95_s": run_metrics.wait_time_s.p95_s,
            "max_s": run_metrics.wait_time_s.max_s,
        },
    }
    if controller == "acamp":
        # The controller's own decision accounting, summed over junctions.
        # M4's "100% of phase changes were max_green timeouts" needed a
        # separate instrumented rerun to discover; here every gate run
        # reports it for free.
        totals: dict[str, int] = {}
        for ctrl in strategy.values():
            for key, value in ctrl.stats.items():
                totals[key] = totals.get(key, 0) + value
        record["decision_stats"] = totals
        if record_baseline and load_baseline is not None:
            # Harvest each junction's ending slow-EWMA as the value the
            # *next* run for that junction starts from -- see
            # `LoadBaseline.update`'s docstring for why this overwrites
            # rather than blends. Deliberately unconditional on
            # `use_relative_congestion_gate`: `_update_load` folds every
            # tick into both EWMAs regardless of whether the gate reads
            # the ratio, so a warm-up run's *decisions* are identical to
            # an ordinary frozen-default run -- only the harvested number
            # differs.
            for tls_id, ctrl in strategy.items():
                load_baseline.update(tls_id, ctrl.baseline_load)
    try:
        tripinfo_path.unlink()  # scorecard extracted; the XML is large
    except OSError:
        pass
    return record
