"""M7 gate: does the Green Corridor Engine actually help, and what does
it cost?

Three arms, paired on seed, over the same `EVAL_SEEDS` every previous
milestone's gate used:

    none       A-CA-MP, no preemption at all. The emergency vehicle is an
               ordinary vehicle with an emergency vClass, taking whatever
               the adaptive controller happens to give it.
    reactive   Per-junction preemption on a fixed detection range, each
               junction deciding independently. This is what the field
               deploys and what the literature measures, and it is the
               arm the corridor engine has to beat -- not `none`. Beating
               `none` only shows that preemption works, which has been
               known since the 1970s.
    corridor   The full engine: route-level arbitration, lead time
               computed from transfer plus queue discharge, coalescing,
               bounded release, plus A-CA-MP's A(p) and D(p) terms.

**What is measured, and why it is not one number.** H9's argument is that
reporting EVP as a mean is the operation that makes its cost invisible:
the delay burden is real, it is large, and it lands on the same
identifiable movements every time. Reno found EVP worsens operations for
*all five* of its exit strategies; a Route 7 study's much-quoted 1.6%
travel-time increase came with an explicit caveat that it may not
generalise to corridors with closer spacing and shorter cycles, which
describes this one. So this reports the emergency vehicle's benefit and
the cross street's cost side by side, plus the per-movement debt
distribution, and never a single combined score.

`--arms` and `--seeds` narrow a run; the defaults are the full gate.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import traci

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "experiments"))
sys.path.insert(0, str(_ROOT / "data" / "scenarios" / "networks" / "vijayawada"))
# Both paths are inserted *here*, not inherited from `m5_harness`. That
# module inserts the scenario directory as a side effect of its own
# import, and this file relied on it -- which held only while
# `m5_harness` happened to be imported before `link_lanes`. An import
# sort put `link_lanes` first and the script stopped starting at all.
# Depending on another module's import side effect for your own path is
# a dependency the sorter cannot see.

from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
from m5_harness import (  # noqa: E402
    ARTIFACT_DIR,
    EVAL_SEEDS,
    MAX_STEPS_SAFETY_CAP,
    NET_PATH,
    build_acamp,
    scenario_inputs,
)
from sim_service.control import metrics  # noqa: E402
from sim_service.control.corridor import (  # noqa: E402
    CorridorConfig,
    CorridorEngine,
    PreemptionClass,
)
from sim_service.control.dispatch import (  # noqa: E402
    DispatchDecision,
    FacilityIndex,
    IncidentRequest,
    choose,
)
from sim_service.control.runner import run_controlled_scenario  # noqa: E402
from sim_service.control.strategies import acamp  # noqa: E402
from sim_service.signal_controller.ev_detection import (  # noqa: E402
    EmergencyVehicleReporter,
    build_movement_index,
)
from sim_service.signal_controller.ev_routing import edge_latlon, traci_route_fn  # noqa: E402

FACILITIES_PATH = _ROOT / "data" / "scenarios" / "networks" / "vijayawada" / "facilities.json"

EV_INCIDENT = IncidentRequest(
    incident_id="INC-TRAUMA",
    origin_edge="219187869",
    origin_lat=0.0,  # filled from the network at run start; see `_Injector`
    origin_lon=0.0,
    required_capability="trauma",
)
"""The call for service the benchmark's emergency vehicles answer.

The route is **not** written down here. It is what `dispatch.choose`
returns for this incident against the facility register, computed once
per run at t = 0, and the reason that is worth the indirection is that
the previous version *was* written down -- a nine-edge arterial pasted
into this file, which is the thing the whole dispatch layer exists to
stop being necessary.

**Why a trauma call, and not the obvious general one.** Because a general
call measured out as the wrong scenario for a corridor benchmark, and the
measurement is worth stating rather than the conclusion. Routing a
`general` incident from each of the nineteen approach edges into these
seven junctions gives a response that touches **at most 2 of the 7**, a
median of 1, and none at all from seven of them; travel times run 6 to
60 seconds. That is not a failure of dispatch -- it is what 48 general
facilities inside a 4 km box means. The nearest hospital is always a
block away, and a green corridor is irrelevant to a 22-second trip.

Scarcity is what makes a corridor worth having, here and in the field:
this extract has exactly one `trauma` facility, so a trauma patient goes
there whatever the distance. Dispatching trauma from this origin returns
a route through **all seven junctions in order**, 144 s free-flow. The
same origin gives 6 of 7 for `ent` (n=3) and `dental` (n=5), 5 of 7 for
`oncology` (n=4).

**What this changed, and what it did not.** The dispatch route and the
old hand-picked one share 8 of 9 edges and traverse the same seven
junctions in the same order; they differ only in the final edge, where
the hand-picked route ran on to the bounding box and the dispatched one
stops at the hospital. So the gate is measuring the same manoeuvre it
always was -- but it is now measuring a route the system *derived*, and
the absolute EV durations shifted enough with that last edge that the
recorded numbers were re-measured rather than carried over."""

EV_DEPARTURES_S = (300.0, 700.0, 1100.0, 1500.0)
"""Four responses in a 1800 s run. Chosen to be frequent enough that the
budget, the debt ledger and the recovery interact -- F8's "preemption
during transition" and F3's cross-street starvation only appear when
events are close enough together to overlap -- and infrequent enough that
the corridor is not permanently preempted, which would measure something
nobody deploys."""

EV_VTYPE = "veh_emergency"
_EV_PREFIX = "EV"


@dataclass
class _Arm:
    name: str
    corridor: CorridorEngine | None
    acamp_cfg: acamp.AcampConfig


class ReactivePreemption(CorridorEngine):
    """The field-standard baseline: each junction preempts on its own
    fixed detection range, with no corridor-level anything.

    Written as a subclass so the *difference* is the only thing in the
    file, and so both arms share the identical safety machinery -- the
    per-junction state machine, the interlock pre-checks, the bounded
    release. That matters for attribution: whatever the corridor arm wins
    is then attributable to route-level coordination and not to a safety
    kernel one arm has and the other does not.

    Three behaviours are removed relative to the corridor engine, and
    each is a specific catalogued weakness of the deployed design:

    - **Fixed range instead of computed lead time.** 300 m, in the band
      real installations use (Fairfax County about 1,600 ft, St. Paul up
      to about 2,300 ft for fast-accelerating police vehicles). This is
      E1 and G4's shared root cause: a range is a proxy for readiness,
      and it is wrong in both directions.
    - **No corridor arbitration.** Every junction resolves its own
      contenders. With one emergency vehicle this cannot differ from the
      corridor arm; with two on crossing routes it is D11.
    - **No anticipation and no debt** -- `A(p)` and `D(p)` are zeroed by
      giving this arm an `AcampConfig` with both weights at zero, so the
      controller underneath is exactly M5's.
    """

    detection_range_m = 300.0

    def _should_claim(self, cfg, ctx, track, target, movement) -> bool:
        distance = track.report.distance_to_m.get(cfg.intersection_id)
        return distance is not None and distance <= self.detection_range_m

    def _arbitrate(self, now_s):
        # Per junction, first-come-first-served among accepted tracks, no
        # coalescing and no class ordering across junctions -- each
        # junction sees only its own contenders.
        winners: dict[str, str] = {}
        for track in sorted(self._tracks.values(), key=lambda t: t.first_seen_s):
            if not track.accepted(now_s, self.cfg):
                continue
            for junction_id in track.report.route:
                winners.setdefault(junction_id, track.vehicle_id)
        return winners

    def anticipation(self, junction_id):
        return {}


class _Injector:
    """Adds the emergency vehicles at their departure times, then hands
    every tick to the reporter.

    Injection happens through TraCI rather than through the route file so
    that all three arms run the *same* demand file, seed for seed. A
    route file with the emergency vehicle written into it would be a
    different file from the one M4 and M5 measured against, and the
    cross-street numbers would no longer sit in the same table as
    theirs."""

    def __init__(
        self,
        reporter: EmergencyVehicleReporter | None,
        incident: IncidentRequest = EV_INCIDENT,
    ) -> None:
        self._reporter = reporter
        self._added: set[str] = set()
        self._prepared = False
        self.incident = incident
        """The gate always uses `EV_INCIDENT`; the parameter exists so
        `m7_demo.py` can vary the capability and show what the general
        case actually looks like -- a hospital two blocks away and a
        corridor that never comes into it."""
        self.decision: DispatchDecision | None = None
        """The dispatch that produced this run's route, kept so the record
        can say which facility was chosen and out of how many. A route
        with no decision behind it is the state this benchmark used to be
        in and the one worth being able to rule out from the artefact."""
        self.facilities: FacilityIndex | None = None

    def _dispatch(self) -> DispatchDecision:
        """Where this run's emergency vehicles are going.

        Run once, at t = 0, on the empty network -- so every arm gets the
        identical route and the comparison stays paired. That is a
        deliberate departure from how dispatch is meant to work, and it
        is the right departure *for this experiment*: routing against
        live conditions would let the arms diverge onto different
        destinations, and an emergency-vehicle travel time measured
        against a different hospital in each arm is not a comparison at
        all. Live re-dispatch is what `m7_demo.py` shows and what
        `should_redispatch` is for; a controlled experiment is the one
        place it must be held fixed."""
        lat, lon = edge_latlon(self.incident.origin_edge)
        self.incident = replace(self.incident, origin_lat=lat, origin_lon=lon)
        self.facilities = FacilityIndex.from_json(FACILITIES_PATH)
        decision = choose(self.incident, self.facilities, traci_route_fn(EV_VTYPE))
        if decision is None:
            # Loudly, and without a fallback route. A silent fallback here
            # would produce a run that looks like every other run and
            # measures a different trip -- the failure mode this whole
            # change exists to remove.
            raise RuntimeError(
                f"no reachable {self.incident.required_capability!r} facility from "
                f"{self.incident.origin_edge!r}; regenerate facilities.json"
            )
        return decision

    def _prepare(self) -> None:
        if self._prepared:
            return
        self._prepared = True
        try:
            traci.vehicletype.copy("veh_car", EV_VTYPE)
        except traci.TraCIException:
            pass
        traci.vehicletype.setVehicleClass(EV_VTYPE, "emergency")
        # Faster and more assertive than the general traffic, which is
        # what makes the emergency-vehicle travel time a meaningful
        # measurement rather than a copy of everyone else's.
        traci.vehicletype.setMaxSpeed(EV_VTYPE, 22.0)
        traci.vehicletype.setAccel(EV_VTYPE, 3.0)
        traci.vehicletype.setImperfection(EV_VTYPE, 0.0)
        # After the vehicle type exists, because the route is computed
        # *for* it: an emergency vClass is permitted on edges a car is
        # not, and routing as a car would quietly return a worse
        # facility rather than an error.
        self.decision = self._dispatch()
        try:
            traci.route.add("ev_corridor", self.decision.route_edges)
        except traci.TraCIException:
            pass

    def __call__(self, now_s: float) -> None:
        self._prepare()
        for i, depart in enumerate(EV_DEPARTURES_S):
            vid = f"{_EV_PREFIX}{i}"
            if vid in self._added or now_s < depart:
                continue
            self._added.add(vid)
            traci.vehicle.add(vid, "ev_corridor", typeID=EV_VTYPE, departSpeed="max")
            # SUMO's emergency vClass may pass red on its own if allowed;
            # this build measures what the *signals* do, so that override
            # stays off and the emergency vehicle obeys every indication.
            traci.vehicle.setSpeedMode(vid, 31)
        if self._reporter is not None:
            self._reporter(now_s)


def ev_vehicle_ids() -> frozenset[str]:
    return frozenset(f"{_EV_PREFIX}{i}" for i in range(len(EV_DEPARTURES_S)))


def build_arm(name: str) -> _Arm:
    """Five arms, three of which exist only to attribute a loss.

    The first gate run produced a clear negative result: the full
    corridor arm was worse than `reactive` on *both* axes -- the
    emergency vehicle slower (837 s against 711 s mean) and the cross
    street paying more (314k against 245k person-delay). A 28% delay
    increase is far more than the ~205 s of preemption a run actually
    spends can account for, so the suspect is the pressure terms rather
    than the preemption policy.

    Two things differ between `reactive` and `corridor`, and a
    two-arm comparison cannot separate them: the preemption policy
    (fixed range against computed lead time) and the pressure function
    (`A(p)`/`D(p)` on against off). `corridor_noAD` isolates the first
    and `corridor_noD` the second."""
    zeroed = acamp.AcampConfig(lambda_anticipation=0.0, lambda_debt=0.0)
    if name == "none":
        return _Arm("none", None, zeroed)
    authorized = dict.fromkeys(ev_vehicle_ids(), PreemptionClass.FIRE)
    if name == "reactive":
        return _Arm("reactive", ReactivePreemption(authorized=authorized), zeroed)
    configs = {
        # Preemption policy differs from `reactive`, pressure function
        # does not: isolates the lead-time trigger on its own.
        "corridor_noAD": zeroed,
        # Anticipation on, debt off: isolates `D(p)`, the term whose
        # magnitude is least obviously bounded.
        "corridor_noD": acamp.AcampConfig(lambda_debt=0.0),
        "corridor": acamp.AcampConfig(),
    }
    if name in configs:
        return _Arm(
            name,
            CorridorEngine(CorridorConfig(), authorized=authorized),
            configs[name],
        )
    raise ValueError(f"unknown arm {name!r}")


def run_one(arm_name: str, demand_level: str, seed: int, inputs=None) -> dict:
    configs, flows, vtype_pcu, paths = inputs or scenario_inputs(demand_level)
    arm = build_arm(arm_name)
    link_lanes = link_to_lane_map(NET_PATH)
    receiving_lanes = link_to_receiving_lane_map(NET_PATH)

    strategy = build_acamp(configs, flows, acamp_cfg=arm.acamp_cfg)
    if arm.corridor is not None:
        for controller in strategy.values():
            controller.corridor = arm.corridor

    reporter = None
    if arm.corridor is not None:
        index = build_movement_index(link_lanes, receiving_lanes, configs)
        reporter = EmergencyVehicleReporter(arm.corridor, index, ev_vehicle_ids())
    injector = _Injector(reporter)

    tripinfo_dir = ARTIFACT_DIR / "m7_tripinfo"
    tripinfo_dir.mkdir(parents=True, exist_ok=True)
    tripinfo_path = tripinfo_dir / f"{arm_name}_{demand_level}_seed{seed}.xml"

    result = run_controlled_scenario(
        str(paths["sumocfg"]),
        configs,
        strategy=strategy,
        seed=seed,
        link_lanes=link_lanes,
        receiving_lanes=receiving_lanes,
        vtype_pcu=vtype_pcu,
        tripinfo_output=str(tripinfo_path),
        max_steps=MAX_STEPS_SAFETY_CAP,
        corridor=arm.corridor,
        ev_reporter=injector,
    )

    trips = metrics.parse_tripinfo(tripinfo_path)
    run_metrics = metrics.compute_run_metrics(tripinfo_path, paths["route"])
    ev_ids = ev_vehicle_ids()
    ev_trips = [t for t in trips if t.vehicle_id in ev_ids]

    record: dict = {
        "arm": arm_name,
        "demand_level": demand_level,
        "seed": seed,
        "steps": result["steps"],
        "interlock_violations": result["interlock_violations"],
        # Which junction and which failsafe mode, not just how many.
        # `interlock_violations` alone cannot say whether a rejection came
        # from the corridor rung or from the strategy below it, and the
        # answer matters: the engine's own counter `denied_by_interlock`
        # covers rung 3, so anything left over is A-CA-MP's. Four
        # violations appeared in the heavy-demand corridor arm with
        # `denied_by_interlock` at zero on every run, which places them
        # in the strategy -- but the junction and mode were not recorded,
        # so that had to be inferred rather than read.
        "fault_events": [
            {"junction": j, "step": st, "mode": m} for j, st, m in result["fault_events"]
        ],
        # Everyone who is not an emergency vehicle -- the party that pays.
        "person_delay_s": run_metrics.person_delay_s,
        "wait_p95_s": run_metrics.wait_time_s.p95_s,
        "wait_max_s": run_metrics.wait_time_s.max_s,
        "n_ev_completed": len(ev_trips),
        "ev_duration_s": sum(t.duration_s for t in ev_trips),
        "ev_time_loss_s": sum(t.time_loss_s for t in ev_trips),
        "ev_waiting_time_s": sum(t.waiting_time_s for t in ev_trips),
        "ev_stops": sum(t.waiting_count for t in ev_trips),
    }
    # Which facility this run's vehicles were actually sent to. Recorded
    # because the route is now derived rather than declared: if a future
    # facility register moves the trauma centre, the gate's numbers move
    # with it, and the artefact should say so rather than leaving the
    # change to be inferred from a shifted mean.
    if injector.decision is not None:
        record["dispatch"] = {
            "incident": injector.incident.incident_id,
            "capability": injector.incident.required_capability,
            "origin_edge": injector.incident.origin_edge,
            "facility": injector.decision.facility.name,
            "facility_id": injector.decision.facility.id,
            "free_flow_travel_time_s": injector.decision.travel_time_s,
            "considered": injector.decision.considered,
            "unreachable": injector.decision.unreachable,
            "route_edges": list(injector.decision.route_edges),
        }
    # The controller's own decision accounting, summed over junctions.
    # Added to answer a question the run-level metrics cannot: A(p) and
    # D(p) are identically zero except while a response is running, so
    # before tuning them it is worth knowing how many ticks they were
    # even non-zero on. A term active on 2% of ticks cannot move an
    # 1800-second average, however well tuned.
    totals: dict[str, int] = {}
    for controller in strategy.values():
        for key, value in controller.stats.items():
            totals[key] = totals.get(key, 0) + value
    record["decision_stats"] = totals

    if arm.corridor is not None:
        stats = arm.corridor.stats()
        record["corridor"] = {k: v for k, v in stats.items() if not k.startswith("preempted_s/")}
        record["preempt_seconds_total"] = float(stats.get("preempted_s", 0.0))
        record["debt_by_movement"] = dict(arm.corridor.debt.report())
        record["ev_passages"] = dict(reporter.passages) if reporter else {}
    try:
        tripinfo_path.unlink()
    except OSError:
        pass
    return record


def _paired(records: list[dict], arm_a: str, arm_b: str, key: str) -> dict:
    """Paired difference `b - a` on the shared seeds, with a 95% interval.

    Paired because the two arms ran the identical seed, so the
    seed-to-seed variance -- which dominates everything on this corridor
    -- cancels. Unpaired comparison of ten stochastic runs against ten
    others would produce an interval wide enough to contain any result
    anyone wanted."""
    by_seed_a = {r["seed"]: r[key] for r in records if r["arm"] == arm_a}
    by_seed_b = {r["seed"]: r[key] for r in records if r["arm"] == arm_b}
    seeds = sorted(set(by_seed_a) & set(by_seed_b))
    diffs = [by_seed_b[s] - by_seed_a[s] for s in seeds]
    if len(diffs) < 2:
        return {"n": len(diffs), "mean": diffs[0] if diffs else None}
    mean = statistics.fmean(diffs)
    sd = statistics.stdev(diffs)
    half = 2.262 * sd / (len(diffs) ** 0.5)  # t(0.975, df=9)
    return {
        "n": len(diffs),
        "mean": mean,
        "ci95": [mean - half, mean + half],
        "significant": (mean - half) * (mean + half) > 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", nargs="+", default=["none", "reactive", "corridor"])
    parser.add_argument("--demand", nargs="+", default=["medium"])
    parser.add_argument("--seeds", nargs="+", type=int, default=EVAL_SEEDS)
    parser.add_argument("--out", default=str(ARTIFACT_DIR / "m7_corridor_gate.json"))
    args = parser.parse_args()

    records: list[dict] = []
    for demand_level in args.demand:
        inputs = scenario_inputs(demand_level)
        for arm_name in args.arms:
            for seed in args.seeds:
                record = run_one(arm_name, demand_level, seed, inputs=inputs)
                records.append(record)
                print(
                    f"{arm_name:9s} {demand_level:6s} seed {seed:3d}  "
                    f"EV {record['ev_duration_s']:7.1f}s "
                    f"(loss {record['ev_time_loss_s']:6.1f}s, "
                    f"stops {record['ev_stops']:3d})  "
                    f"person_delay {record['person_delay_s']:10.0f}  "
                    f"viol {record['interlock_violations']}",
                    flush=True,
                )

    summary: dict = {"records": records, "comparisons": {}}
    for demand_level in args.demand:
        subset = [r for r in records if r["demand_level"] == demand_level]
        for base, arm in (("none", "reactive"), ("none", "corridor"), ("reactive", "corridor")):
            if base not in args.arms or arm not in args.arms:
                continue
            summary["comparisons"][f"{demand_level}:{arm}-vs-{base}"] = {
                metric: _paired(subset, base, arm, metric)
                for metric in (
                    "ev_duration_s",
                    "ev_time_loss_s",
                    "ev_stops",
                    "person_delay_s",
                    "wait_p95_s",
                    "wait_max_s",
                )
            }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nwrote {out}")

    for label, block in summary["comparisons"].items():
        print(f"\n{label}")
        for metric, stat in block.items():
            if "ci95" not in stat:
                continue
            mark = "*" if stat["significant"] else " "
            print(
                f"  {mark} {metric:18s} {stat['mean']:+10.2f}  "
                f"[{stat['ci95'][0]:+9.2f}, {stat['ci95'][1]:+9.2f}]"
            )


if __name__ == "__main__":
    main()
