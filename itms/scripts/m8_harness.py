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
from dataclasses import replace
from functools import cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from itms_domain.lane_chains import SHORT_APPROACH_M  # noqa: E402
from itms_domain.overlaps import (  # noqa: E402
    pedestrian_links,
    turnaround_links,
    with_overlaps,
)
from itms_domain.phase_layout import compact_layout, net_links, paired_layout  # noqa: E402
from itms_geo import RoadNetwork  # noqa: E402
from m5_ccacamp_gate import _ARMS, CEILING_FACTOR  # noqa: E402
from m5_cycle_ceiling_probe import (  # noqa: E402
    configs_with_ceiling,
    max_wait_for,
    webster_ceilings,
)
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


CEILING_FLOOR_S = 20.0
"""No phase's green ceiling is below this (seconds). Adopted 2026-10-07
(`baselines/2026-10-07_ceiling_floor`): held-out, -4.6 % [-7.2, -1.9]
person-delay over 20 light and medium network-levels, nothing significantly
worse, heavy unchanged; Amaravati plan grid light -16.4 % [-21.2, -11.6].
`truth:f0` and `hol:f0` are the controllers without it."""


# Every phase also *shows* each movement that conflicts with nothing it shows,
# without owning it (`Phase.overlap_movements`; adopted 2026-10-11, held-out
# test baselines/2026-10-11_overlaps). The timing, the controller's pressure,
# demand and gap-out are as without it. `truth:noovl` is the controller before it.
SHOWN_OVERLAPS = True

# A split-phased junction (one phase per approach) is rebuilt with facing
# approaches sharing a phase, the turn across the oncoming stream giving way
# (`itms_domain.phase_layout`; adopted 2026-10-13, held-out test
# baselines/2026-10-13_paired_phases). Other junctions are unchanged.
# `truth:nopair` is the controller before it.
PHASE_LAYOUT: str | None = "pair"


def ccacamp_inputs(level: str, ceiling: float = CEILING_FACTOR,
                   floor_s: float = CEILING_FLOOR_S, overlaps: bool = False,
                   shown_overlaps: bool = SHOWN_OVERLAPS, layout: str | None = PHASE_LAYOUT):
    """`overlaps`: every phase also shows *and owns* each movement that
    conflicts with nothing it shows (`itms_domain.overlaps`), applied before
    Webster's greens and the ceilings are worked out -- the first form, kept
    for the record (heavy demand +70 % on arterial_lh). `shown_overlaps`: the
    adopted form, added after the timing and not owned. `layout`: "pair" or
    "pairt" rebuild split-phased junctions (`itms_domain.phase_layout`) before
    anything else is worked out."""
    if floor_s <= 0.0:
        inputs = configs_with_ceiling(_scenario_inputs(level, overlaps, layout), ceiling)
    else:
        inputs = ccacamp_inputs_with_floor(level, floor_s, ceiling, overlaps, layout)
    return overlaps_kept_timing(inputs, owned=False) if shown_overlaps else inputs


def overlaps_kept_timing(inputs, owned: bool = True, uturns: bool = True):
    """`inputs` with every phase also showing the movements that conflict with
    nothing it shows (`itms_domain.overlaps`), *after* the green ceilings and
    wait bounds were worked out: only the greens change, not the timing.
    (`overlaps=True` above applies them first, and Webster then splits the cycle
    as if each overlap movement loaded every phase it is in: on arterial_lh at
    heavy demand the main road's ceilings fell from about 80 s to 51 s, +70 %
    person-delay on training seeds, 2026-10-11.) Build the controller from the
    configs without overlaps, so its nominal cycle is unchanged too."""
    configs, flows, pcu, paths = inputs
    walk = pedestrian_links(H.NET_PATH)
    turn = {} if uturns else turnaround_links(H.NET_PATH)
    return ({tls: with_overlaps(cfg, walk.get(tls, frozenset()) | turn.get(tls, frozenset()), owned)
             for tls, cfg in configs.items()}, flows, pcu, paths)


def _scenario_inputs(level: str, overlaps: bool = False, layout: str | None = None):
    configs, flows, pcu, paths = H.scenario_inputs(level)
    if layout is not None:
        links, heading, lefthand = net_links(H.NET_PATH)
        if layout == "compact":
            configs = {tls: compact_layout(cfg, links.get(tls, {}), heading, lefthand)
                       for tls, cfg in configs.items()}
        else:
            configs = {tls: paired_layout(cfg, links.get(tls, {}), heading, lefthand,
                                          turn_phases=layout == "pairt")
                       for tls, cfg in configs.items()}
    if overlaps:
        walk = pedestrian_links(H.NET_PATH)
        configs = {tls: with_overlaps(cfg, walk.get(tls, ())) for tls, cfg in configs.items()}
    return configs, flows, pcu, paths


def ccacamp_inputs_with_floor(level: str, floor_s: float, ceiling: float = CEILING_FACTOR,
                              overlaps: bool = False, layout: str | None = None):
    """CC-A-CAMP's inputs with no phase's green ceiling below `floor_s`.

    The ceiling is `ceiling` times Webster's green. At light demand Webster
    returns its minimum cycle, so on a four-phase junction the ceiling is under
    9 s: the controller is forced off a green every few vehicles and pays a
    change interval each time (the planned Amaravati grid, light demand: 69 %
    of all changes were forced by the ceiling, mean wait 48 s against 31 s at
    heavy demand). A floor leaves heavy demand, where Webster's greens are
    longer than the floor, as it was."""
    if floor_s <= 0.0:
        return configs_with_ceiling(_scenario_inputs(level, overlaps, layout), ceiling)
    configs, flows, pcu, paths = _scenario_inputs(level, overlaps, layout)
    out = {}
    for tls, cfg in configs.items():
        ceilings = {p: max(g, floor_s)
                    for p, g in webster_ceilings(cfg, flows.get(tls, {}), ceiling).items()}
        out[tls] = replace(cfg, max_green_s=ceilings, max_wait_s=max_wait_for(cfg, ceilings))
    return out, flows, pcu, paths


# The head-of-line-aware controller (`strategies/hol_camp.py`): CC-A-CAMP's
# settings, plus pricing of blocked lanes ("hol:price") and split variants
# for blocked approaches ("hol").
# The settings of revision 6 (the held-out run of 2026-10-05), which are the
# defaults of `HolConfig`: p0:b3 was the default for a day (2026-10-05, dev23-dev28,
# held-out run 3), did not hold up on fresh seeds and was taken back. Spelled out
# here so that these names mean the same whatever the default is.
_REV6 = {"min_blocked_changes": 1.0, "family_budget": 2.0, "wide_guard": False}
HOL_ARMS = {"hol": HolConfig(), "hol:rev6": HolConfig(**_REV6),
            "hol:price": HolConfig(use_variants=False, **_REV6),
            "hol:p0": HolConfig(**{**_REV6, "min_blocked_changes": 0.0}),
            # multi-lane approaches get variants too: for any blocked lane (the
            # first version), or only while the whole approach is stalled
            "hol:lane": HolConfig(single_lane_only=False, whole_approach=False, **_REV6),
            "hol:multi": HolConfig(single_lane_only=False, **_REV6),
            # ways out of a variant: back to the base phase whenever it would
            # release more; never while another phase waits
            "hol:press": HolConfig(exit_by_pressure=True, **_REV6),
            "hol:idle": HolConfig(**_REV6),
            "hol:term": HolConfig(terminal=True, **_REV6),
            "hol:nobudget": HolConfig(**{**_REV6, "family_budget": 1e9}),
            "hol:b3": HolConfig(**{**_REV6, "family_budget": 3.0}),
            # development arms (TRAIN seeds): how much a variant must gain
            "hol:m0.5": HolConfig(variant_gain_margin=0.5, **_REV6),
            "hol:m1": HolConfig(variant_gain_margin=1.0, **_REV6),
            # ... and how long the blockage must have lasted (change intervals)
            "hol:p1": HolConfig(**_REV6),
            "hol:p2": HolConfig(**{**_REV6, "min_blocked_changes": 2.0})}

# Composed development arms, "hol:<mod>[:<mod>...]": p<x> blockage must last x
# change intervals, b<x> family budget, m<x> gain margin, c<x> green ceiling of
# x times Webster's green (the gate's own is `CEILING_FACTOR`), g1 the wide wait guard.
_HOL_MODS = {"p": "min_blocked_changes", "b": "family_budget", "m": "variant_gain_margin",
             "g": "wide_guard"}
# ... and of the parent controller: r<x> the receiving-link occupancy at which its
# gate is shut (`AcampConfig.rho_jam`), k<x> the gate's sharpness (`beta_gate`).
_ACAMP_MODS = {"r": "rho_jam", "k": "beta_gate"}


def hol_acamp(arm: str):
    """The parent controller's settings for a (composed) arm name."""
    over = {}
    if not dict.__contains__(HOL_ARMS, arm):
        for tok in arm.split(":")[1:]:
            if tok[:1] in _ACAMP_MODS:
                over[_ACAMP_MODS[tok[:1]]] = float(tok[1:])
    return replace(_ARMS["ccacamp"], **over) if over else _ARMS["ccacamp"]


def _composed(arm: str):
    """(HolConfig, ceiling) of a composed arm name, or None if it is not one."""
    if not arm.startswith("hol:"):
        return None
    kw, ceiling = {}, CEILING_FACTOR
    for tok in arm.split(":")[1:]:
        try:
            value = float(tok[1:])
        except ValueError:
            return None
        if tok[:1] == "c":
            ceiling = value
        elif tok[:1] in ("r", "k", "f"):
            continue  # the parent's settings (`hol_acamp`), the ceiling's floor (`hol_floor`)
        elif tok[:1] == "g":
            kw["wide_guard"] = bool(value)
        elif tok[:1] in _HOL_MODS:
            kw[_HOL_MODS[tok[:1]]] = value
        else:
            return None
    return HolConfig(**kw), ceiling


class _HolArms(dict):
    def __contains__(self, arm) -> bool:
        return dict.__contains__(self, arm) or _composed(arm) is not None

    def __missing__(self, arm):
        made = _composed(arm)
        if made is None:
            raise KeyError(arm)
        return made[0]


HOL_ARMS = _HolArms(HOL_ARMS)


def hol_ceiling(arm: str) -> float:
    made = None if dict.__contains__(HOL_ARMS, arm) else _composed(arm)
    return CEILING_FACTOR if made is None else made[1]


def hol_floor(arm: str) -> float:
    """The floor under the green ceiling for an arm: the default for "hol" and
    composed names (f<seconds> overrides it), none for the named historical arms,
    which were measured before the floor existed."""
    if arm == "hol":
        return CEILING_FLOOR_S
    if dict.__contains__(HOL_ARMS, arm):
        return 0.0
    for tok in arm.split(":")[1:]:
        if tok[:1] == "f":
            return float(tok[1:])
    return CEILING_FLOOR_S


@cache
def _internal_links():
    return hol.internal_links(H.NET_PATH)


@cache
def _pedestrian_links():
    return hol.pedestrian_links(H.NET_PATH)


def hol_inputs(level: str, single_lane_only: bool = True, ceiling: float = CEILING_FACTOR,
               floor_s: float = CEILING_FLOOR_S):
    """CC-A-CAMP's inputs with each junction's split variants added to its
    phases (not to its ring), and `{tls: {variant: base}}`."""
    configs, flows, pcu, paths = ccacamp_inputs(level, ceiling, floor_s,
                                                shown_overlaps=False, layout=None)
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
            hol_acamp(arm),
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
    vias: bool = True,
    detector_upstream: bool = True,
    vias_short_m: float | None = SHORT_APPROACH_M,
    arrival_horizon_s: float | None = None,
) -> dict:
    """One scenario, scored with the project's own metrics (person delay,
    stops, throughput, waits), plus the runner's interlock count.
    `runner_kwargs` go straight to `run_controlled_scenario` (for instance
    M6's `anomaly_graph` and `anomaly_feature_sink`)."""
    if controller in HOL_ARMS:
        arm = HOL_ARMS[controller]
        inputs, base_of = hol_inputs(level, arm.single_lane_only, hol_ceiling(controller),
                                     hol_floor(controller))
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
        if vias and H.lane_vias(vias_short_m) is not None:
            # every waiting vehicle is seen (adopted 2026-10-07): those standing
            # between the pieces of a split road, or before a stop-line lane too
            # short to hold them, count toward the queue and raise a call
            kwargs["lane_vias"] = H.lane_vias(vias_short_m)
            kwargs["detector_upstream"] = detector_upstream
    if arrival_horizon_s is not None and controller != "webster":
        kwargs["arrival_horizon_s"] = arrival_horizon_s
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
        "wait_overruns": result.get("wait_overruns"),
        "unfinished_at_cap": result.get("unfinished_at_cap"),
        "person_delay_s": m.person_delay_s,
        "entry_delay_s": m.entry_delay_person_s,
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
