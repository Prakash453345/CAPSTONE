"""Measure real per-movement saturation flow (`s_lm` [build guide §3.9]) on
the real Vijayawada corridor network, replacing `extract_tier0_config.py`'s
uniform placeholder (`_SAT_FLOW_PCU_S = 0.5`) -- the concrete next step
PROGRESS.md's CA-MP switching-cost fix left open: `_switch`'s fix (see
`camp.py`) brought the switching-cost term onto the same `sat_flow_pcu_s`-
weighted scale as every other pressure term, but both terms are still
anchored to one conventional per-lane placeholder rather than this
corridor's real per-approach capacity, which is the remaining reason
CA-MP's pressure function doesn't yet drive real decisions at the demand
levels tested.

**Method** -- the textbook definition of saturation flow, done directly on
the real network rather than a synthetic proxy scenario (this project has
the real geometry and real vType mix already; no reason to approximate
either): for each signal-controlled movement (`L{i}`, one specific SUMO
lane-to-lane connection -- see `link_lanes.py`), isolate it entirely (every
other movement at that junction stays red, and no other traffic is ever
present -- saturation flow is *unimpeded* discharge capacity by
definition, so cross-junction interference would bias it, not model it
more realistically), queue a heavy backlog of vehicles on its approach
lane, hold it green continuously, and record the real simulation-time
instant each queued vehicle crosses the stop line (transitions from the
approach edge onto the exact downstream edge that connection feeds).
Discard the first `_DISCARD_N` crossings (the same "vehicles past the
first few" convention `camp.py`'s own `startup_lost_s` already assumes --
the initial reaction-time/acceleration wave is not steady-state discharge)
and compute a PCU-weighted throughput rate over the remainder: `sum(pcu of
retained vehicles) / (time of last retained crossing - time of first
retained crossing)`, directly in PCU/s -- not raw veh/s scaled by an
average PCU factor afterward, since that would misweight a lane whose
retained sample happens to be mix-skewed.

**Why this needs no new demand assumption**: the vehicle mix used to fill
each queue is the *exact* mix `assign_vtypes.py` already committed to for
this corridor (35% motorcycle / 40% car / 20% auto / 5% bus, same PCU
priors) -- imported from that module, not re-declared, so recalibrating
saturation flow can never quietly drift from the mix the rest of this
project's demand already assumes. A different, unmeasured assumption this
step does carry: how *many* vehicles of each type actually use each lane
in practice may not match this corridor-wide mix per-approach (a bus lane
would see more buses) -- this project has no per-approach mix data, so
applies the one mix it has everywhere, same honesty level as
`assign_vtypes.py`'s own module docstring already flags for demand
generation.

**What this deliberately does not do**: recalibrate `_MIN_GREEN_S`/
`_MAX_GREEN_S`/`_ALL_RED_S`/etc. -- those are safety-engineering choices
(I3's floor, a conventional ceiling, a real clearance interval), not
capacity measurements, and are out of scope here. Also does not touch
`camp.py` itself -- `_switch`'s fix already made it price whatever
`sat_flow_pcu_s` values it's given consistently; this script only changes
what those values *are*.

Usage: `python measure_saturation_flow.py [path/to/vijayawada_corridor.net.xml]`
Writes `sat_flow_calibration.json` next to the net file: `{tls_id: {"L{i}":
pcu_per_s}}`. A movement that couldn't collect enough clean discharges
(see `_MIN_RETAINED`) is *omitted*, not filled with a guess -- callers
should fall back to the existing placeholder for anything missing, and
this script says so plainly in its own summary rather than silently
padding the file.

Not part of the pytest suite, same reason `m4_camp_diagnostics.py` isn't:
shells out to a real SUMO/TraCI process, one per junction.
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path

import traci

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "scenarios" / "networks" / "vijayawada"))
sys.path.insert(0, str(_ROOT / "scenarios" / "demand" / "vijayawada"))
sys.path.insert(0, str(_ROOT / "services" / "sim-service" / "sim_service"))
sys.path.insert(0, str(_ROOT / "services" / "sim-service"))

from assign_vtypes import _MIX, _PCU, _VCLASS  # noqa: E402
from extract_tier0_config import load_configs  # noqa: E402
from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
from sim_service.control.runner import _ensure_sumo_home, _resolve_sumo_binary  # noqa: E402

_DEFAULT_NET = _ROOT / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
_SEED = 7  # same seed assign_vtypes.py uses, for the same reason: fixed and documented

# How many vehicles to pre-queue and how long to let them build up before
# going green -- enough depth that even a slow-discharging heavy lane (a
# bus-heavy draw) doesn't run the queue dry before _MIN_RETAINED clean
# crossings are collected.
_QUEUE_DEPTH = 40
_INSERT_INTERVAL_S = 0.5
_RED_BUILDUP_S = _QUEUE_DEPTH * _INSERT_INTERVAL_S + 5.0

# "Vehicles past the first few" -- discarded as the startup-lost-time wave,
# matching camp.py's own CampConfig.startup_lost_s convention rather than
# inventing a separate constant for the same idea.
_DISCARD_N = 4
_TARGET_RETAINED = 25
_MIN_RETAINED = 8  # below this, the sample is too thin to report -- omit, don't guess
_MAX_GREEN_S = 90.0
_STEP_LENGTH = 0.5


def _build_empty_cfg(net_path: Path, tmp_dir: Path) -> Path:
    """A minimal sumocfg pointing at the real network with no scheduled
    demand at all -- every vehicle in a calibration run is inserted live
    via TraCI, not read from a route file. `time-to-teleport` is disabled
    entirely: the whole point of the red-buildup window is a real,
    stationary queue, and SUMO's teleport-on-long-wait behaviour exists to
    rescue a broken *scenario*, not something a deliberate calibration hold
    should ever trigger."""
    route_path = tmp_dir / "empty.rou.xml"
    route_path.write_text('<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>\n')
    cfg_path = tmp_dir / "calibration.sumocfg"
    cfg_path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<configuration>
    <input>
        <net-file value="{net_path.resolve()}"/>
        <route-files value="{route_path.resolve()}"/>
    </input>
    <time>
        <begin value="0"/>
        <step-length value="{_STEP_LENGTH}"/>
    </time>
    <processing>
        <time-to-teleport value="-1"/>
    </processing>
</configuration>
"""
    )
    return cfg_path


def _register_vtypes() -> None:
    for type_id in _MIX:
        traci.vehicletype.copy("DEFAULT_VEHTYPE", type_id)
        traci.vehicletype.setVehicleClass(type_id, _VCLASS[type_id])


def _measure_one_movement(
    tls_id: str,
    link: str,
    from_lane_id: str,
    to_lane_id: str,
    rng: random.Random,
    n_links: int,
) -> dict | None:
    from_edge, from_lane_idx = from_lane_id.rsplit("_", 1)
    to_edge, _ = to_lane_id.rsplit("_", 1)

    route_id = f"calib_{tls_id}_{link}"
    try:
        traci.route.add(route_id, [from_edge, to_edge])
    except traci.exceptions.TraCIException:
        # This movement's fromEdge/toEdge aren't independently routable
        # (e.g. a U-turn or an edge pair duarouter's own network graph
        # doesn't connect the way the raw <connection> claims) -- skip
        # rather than force a route that would silently reroute the
        # vehicle somewhere else and invalidate the measurement.
        return None

    all_red = "r" * n_links
    green_state = all_red[: int(link[1:])] + "G" + all_red[int(link[1:]) + 1 :]
    traci.trafficlight.setRedYellowGreenState(tls_id, all_red)

    type_ids = list(_MIX.keys())
    weights = [_MIX[t] for t in type_ids]
    inserted: dict[str, str] = {}  # vehID -> typeID
    n_inserted = 0
    # Elapsed time *since this movement's own buildup started*, not the
    # absolute simulation clock -- this junction may already be well past
    # t=0 by the time an earlier movement in the same TraCI session
    # finishes. Using the absolute clock here was a real bug caught during
    # this script's own pilot run: the second movement measured in any
    # session got essentially zero buildup time (the `while` condition was
    # already false on entry), producing a near-empty queue instead of a
    # real one -- silently wrong data, not a crash, exactly the kind of
    # thing worth a regression comment.
    buildup_start = traci.simulation.getTime()
    elapsed = 0.0
    while elapsed < _RED_BUILDUP_S:
        traci.simulationStep()
        elapsed = traci.simulation.getTime() - buildup_start
        if elapsed >= n_inserted * _INSERT_INTERVAL_S and n_inserted < _QUEUE_DEPTH:
            veh_id = f"{route_id}_v{n_inserted}"
            vtype = rng.choices(type_ids, weights=weights, k=1)[0]
            try:
                traci.vehicle.add(
                    veh_id,
                    route_id,
                    typeID=vtype,
                    departLane=from_lane_idx,
                    departPos="free",
                    departSpeed="0",
                )
                inserted[veh_id] = vtype
            except traci.exceptions.TraCIException:
                pass  # no room right now -- try again next tick
            n_inserted += 1

    if len(inserted) < _MIN_RETAINED + _DISCARD_N:
        for veh_id in inserted:
            if veh_id in traci.vehicle.getIDList():
                traci.vehicle.remove(veh_id)
        traci.trafficlight.setRedYellowGreenState(tls_id, all_red)
        return {
            "error": f"only {len(inserted)} vehicles queued, needed >= {_MIN_RETAINED + _DISCARD_N}"
        }

    traci.trafficlight.setRedYellowGreenState(tls_id, green_state)
    green_start = traci.simulation.getTime()
    crossings: list[tuple[float, str]] = []
    seen: set[str] = set()
    while (
        traci.simulation.getTime() - green_start < _MAX_GREEN_S
        and len(crossings) < _TARGET_RETAINED + _DISCARD_N
    ):
        traci.simulationStep()
        now = traci.simulation.getTime()
        for veh_id in list(inserted):
            if veh_id in seen:
                continue
            if veh_id not in traci.vehicle.getIDList():
                # already left the network (short to_edge) -- can't happen
                # here but guard anyway
                continue
            if traci.vehicle.getRoadID(veh_id) == to_edge:
                crossings.append((now, inserted[veh_id]))
                seen.add(veh_id)

    for veh_id in inserted:
        if veh_id in traci.vehicle.getIDList():
            traci.vehicle.remove(veh_id)
    traci.trafficlight.setRedYellowGreenState(tls_id, all_red)
    for _ in range(4):  # let removal settle before the next movement's buildup starts
        traci.simulationStep()

    retained = crossings[_DISCARD_N:]
    if len(retained) < _MIN_RETAINED:
        return {
            "error": f"only {len(retained)} clean discharges after discarding "
            f"the first {_DISCARD_N} (of {len(crossings)} total) -- needed >= {_MIN_RETAINED}"
        }

    elapsed_s = retained[-1][0] - retained[0][0]
    total_pcu = sum(
        _PCU[vtype] for _, vtype in retained[1:]
    )  # exclude the first retained vehicle's own (undefined) headway
    if elapsed_s <= 0:
        return {"error": "degenerate: retained crossings had zero elapsed time"}
    sat_flow_pcu_s = total_pcu / elapsed_s
    return {
        "sat_flow_pcu_s": round(sat_flow_pcu_s, 4),
        "n_discharged_total": len(crossings),
        "n_retained": len(retained),
        "elapsed_s": round(elapsed_s, 2),
    }


def _group_links_by_lane(links: list[str], approach_lanes: dict[str, str]) -> dict[str, list[str]]:
    """Real, common geometry in this network: one physical lane sometimes
    feeds *two* signal-controlled `L{i}` entries -- e.g. a straight-through
    lane whose traffic can land on either of a 2-lane receiving edge's
    lanes, which netconvert represents as two separate `<connection>`s
    (two `linkIndex`es) from the same `fromLane`. That's a real ambiguity
    for this script, not just this network's own oddity: a route built as
    a plain edge pair (`[from_edge, to_edge]`) can't tell SUMO which of the
    two same-lane, same-destination-*edge* connections to use when both
    movements share the exact same `(from_lane, to_edge)` pair (only the
    destination *lane* differs) -- confirmed by a pilot run where the
    calibration vehicles queued and started moving, then stopped dead at
    the stop line for the rest of the window, because SUMO had silently
    routed them onto the *other* (still-red) linkIndex from that lane.

    The honest fix is not a routing workaround -- it's recognizing that
    saturation flow is a property of the physical lane doing the
    discharging, not of an abstract movement label. Two `L{i}`s that share
    a `fromLane` share one discharge capacity by construction (the same
    queue, the same stop line, the same vehicles); measuring each
    independently would be measuring the same lane twice under an
    ambiguous route to boot. Group by `fromLane`, measure once per group
    (using the lowest-numbered link in the group to build the route -- an
    arbitrary but deterministic and irrelevant choice, since every link in
    the group shares the same physical lane being measured), and apply
    the one result to every `L{i}` in that group.
    """
    by_lane: dict[str, list[str]] = {}
    for link in links:
        lane = approach_lanes.get(link, f"__unmapped_{link}")
        by_lane.setdefault(lane, []).append(link)
    return by_lane


def measure_corridor(net_path: Path) -> dict:
    configs = load_configs(net_path)
    approach_lanes = link_to_lane_map(net_path)
    receiving_lanes = link_to_receiving_lane_map(net_path)

    _ensure_sumo_home()
    sumo_binary = _resolve_sumo_binary()
    results: dict[str, dict] = {}

    for tls_id, cfg in configs.items():
        all_links: set[str] = set()
        for phase in cfg.phases.values():
            all_links |= phase.green_movements
        links = sorted(all_links, key=lambda link: int(link[1:]))
        lane_groups = _group_links_by_lane(links, approach_lanes.get(tls_id, {}))

        with tempfile.TemporaryDirectory(prefix="itms_satflow_") as tmp:
            cfg_path = _build_empty_cfg(net_path, Path(tmp))
            traci.start([sumo_binary, "-c", str(cfg_path), "--no-warnings", "true"])
            try:
                n_links = len(traci.trafficlight.getRedYellowGreenState(tls_id))
                _register_vtypes()
                rng = random.Random(_SEED)
                junction_results: dict[str, dict] = {}
                for lane_id, group in lane_groups.items():
                    representative = min(group, key=lambda link: int(link[1:]))
                    from_lane = approach_lanes.get(tls_id, {}).get(representative)
                    to_lane = receiving_lanes.get(tls_id, {}).get(representative)
                    if from_lane is None or to_lane is None:
                        outcome = {"error": "no from/to lane mapping"}
                    else:
                        outcome = _measure_one_movement(
                            tls_id, representative, from_lane, to_lane, rng, n_links
                        )
                    outcome = outcome or {"error": "route could not be built"}
                    for link in group:
                        junction_results[link] = dict(outcome)
                    tag = (
                        f"{outcome['sat_flow_pcu_s']:.3f} pcu/s (n={outcome['n_retained']})"
                        if "sat_flow_pcu_s" in outcome
                        else f"SKIPPED -- {outcome.get('error', 'unknown')}"
                    )
                    shared_note = (
                        f" [shared lane -> also {sorted(set(group) - {representative})}]"
                        if len(group) > 1
                        else ""
                    )
                    print(f"  {tls_id} {representative} (lane {lane_id}): {tag}{shared_note}")
                results[tls_id] = junction_results
            finally:
                traci.close()

    return results


def main() -> None:
    net_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_NET
    print(f"measuring real saturation flow on {net_path} ...")
    results = measure_corridor(net_path)

    out_path = net_path.parent / "sat_flow_calibration.json"
    measured = {
        tls: {link: v["sat_flow_pcu_s"] for link, v in links.items() if "sat_flow_pcu_s" in v}
        for tls, links in results.items()
    }
    out_path.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n")

    total = sum(len(links) for links in results.values())
    ok = sum(len(m) for m in measured.values())
    print(f"\nmeasured {ok}/{total} movements; wrote {out_path}")
    if ok < total:
        print(
            f"{total - ok} movement(s) skipped -- callers should fall back "
            "to the placeholder for those:"
        )
        for tls, links in results.items():
            for link, v in links.items():
                if "sat_flow_pcu_s" not in v:
                    print(f"  {tls} {link}: {v.get('error')}")


if __name__ == "__main__":
    main()
