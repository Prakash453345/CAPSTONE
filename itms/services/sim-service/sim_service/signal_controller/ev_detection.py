"""Turns a simulated emergency vehicle into `VehicleReport`s.

Lives beside the other TraCI-touching modules by the same convention
`discharge_observer.py` states: anything that talks to the simulator stays
in this package, and the thing that reasons about the numbers stays a pure
module under `control/`. That split is what keeps `CorridorEngine`
testable without a simulator, and it is also what makes the engine
indifferent to where its observations come from -- an optical detector, a
cellular request, or this.

**Detection here is deliberately perfect, and that is a limitation to
state rather than a convenience to enjoy.** TraCI gives exact position,
speed and route for every vehicle, so this reporter has none of the
failure modes that dominate the real EVP literature: no line-of-sight
occlusion by a truck or a curve (E4/E5), no light trespass onto the wrong
approach (E6), no GPS multipath in an urban canyon (E14), no lens dirt or
tree overgrowth degrading range silently over months (E15), no acoustic
reflection off a building (E12). The engine is built to survive all of
those -- confidence, staleness, the acceptance dwell, geometric release --
but this module cannot *exercise* them, and a benchmark run through it
measures the engine's control behaviour, not its detection robustness.
Degrading these reports on purpose is the natural next experiment and the
hooks for it are already in `VehicleReport`; this module does not do it,
so the corridor numbers are not quietly flattered by a noise model chosen
by whoever also wrote the controller.

**How the route is read.** A junction's movement is identified by the
*pair* of edges it connects: `link_lanes.link_to_lane_map()` gives each
movement's approach lane and `link_to_receiving_lane_map()` gives the lane
it discharges into, so a movement is an ordered edge pair. An emergency
vehicle traverses junction J by movement m exactly when m's (approach,
receiving) pair appears consecutively in its route. That is exact, needs
no geometry, and answers the question D3 says an approach-level request
cannot: *which* movement, not merely which approach -- two units on the
same approach, one continuing through and one turning left across the
opposing through, are served by the same approach and by different
protected paths.
"""

from __future__ import annotations

from collections.abc import Mapping

import traci
from itms_domain import Tier0Config

from sim_service.control.corridor.requests import VehicleReport


def _edge_of(lane_id: str) -> str:
    return lane_id.rsplit("_", 1)[0]


def build_movement_index(
    link_lanes: Mapping[str, Mapping[str, str]],
    receiving_lanes: Mapping[str, Mapping[str, str]],
    configs: Mapping[str, Tier0Config],
) -> dict[tuple[str, str], tuple[str, str]]:
    """`(approach edge, receiving edge) -> (junction id, movement id)`,
    built once per run.

    A pair routinely names more than one movement, and the reason is
    mundane: a three-lane through manoeuvre is three separate links in
    SUMO's connection table, so `219187869 -> 350502993#0` is movements
    L12, L13 and L14 of one junction. They are the same manoeuvre.

    Resolution is by *phase*, not by lane, and that is the whole point.
    What the corridor engine needs from a route is which phase to hold,
    so candidates that share a protected phase are interchangeable for
    its purposes and any of them answers the question. Candidates that do
    not share one are genuinely ambiguous -- the vehicle's chosen lane
    would decide which phase serves it, and a route read ahead of arrival
    cannot see that -- so the pair is dropped.

    The first version of this dropped *every* ambiguous pair, which
    sounded conservative and was useless: it left 31 of the corridor's 73
    movements indexed, and the arterial route through all seven junctions
    resolved to exactly one of them. Refusing to guess is right; refusing
    to answer a question that has a unique correct answer is not.

    Dropping rather than guessing still costs only a preemption. Guessing
    wrong would hand an emergency vehicle a confirmation indication for a
    path that was never cleared, which is hazard D3."""
    from sim_service.control.corridor.junction import protected_phase_for

    candidates: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for tls_id, movements in link_lanes.items():
        receiving = receiving_lanes.get(tls_id, {})
        for movement, approach_lane in movements.items():
            receiving_lane = receiving.get(movement)
            if receiving_lane is None:
                continue
            key = (_edge_of(approach_lane), _edge_of(receiving_lane))
            candidates.setdefault(key, []).append((tls_id, movement))

    index: dict[tuple[str, str], tuple[str, str]] = {}
    for key, hits in candidates.items():
        if len({tls for tls, _ in hits}) > 1:
            continue  # two junctions connect the same edge pair: not resolvable
        tls_id = hits[0][0]
        cfg = configs.get(tls_id)
        if cfg is None:
            continue
        phases = {protected_phase_for(cfg, movement) for _, movement in hits}
        phases.discard(None)
        if len(phases) != 1:
            continue  # candidates disagree about which phase serves them
        phase = phases.pop()
        chosen = next(
            (m for _, m in hits if protected_phase_for(cfg, m) == phase), None
        )
        if chosen is not None:
            index[key] = (tls_id, chosen)
    return index


def junctions_on_route(
    route_edges: tuple[str, ...],
    index: Mapping[tuple[str, str], tuple[str, str]],
) -> list[tuple[str, str, str]]:
    """`[(junction id, movement id, approach edge), ...]` in traversal
    order, for the consecutive edge pairs of `route_edges` that name a
    controlled movement."""
    out: list[tuple[str, str, str]] = []
    for approach, receiving in zip(route_edges, route_edges[1:], strict=False):
        hit = index.get((approach, receiving))
        if hit is not None:
            out.append((hit[0], hit[1], approach))
    return out


class EmergencyVehicleReporter:
    """Observes every emergency vehicle in the running simulation once per
    step and submits one `VehicleReport` each.

    `vehicle_ids` is checked against the live vehicle list every call
    rather than cached, because a vehicle that has not departed yet and
    one that has already arrived both raise on any TraCI query, and both
    happen routinely -- an emergency vehicle inserted at t=300 does not
    exist at t=299, and has left the network well before the run ends."""

    def __init__(
        self,
        engine,
        movement_index: Mapping[tuple[str, str], tuple[str, str]],
        vehicle_ids: frozenset[str],
    ) -> None:
        self._engine = engine
        self._index = movement_index
        self._vehicle_ids = vehicle_ids
        self._routes: dict[str, list[tuple[str, str, str]]] = {}
        self._counted: dict[str, set[str]] = {}
        self.observations = 0
        self.passages: dict[str, int] = {}
        """Junctions each vehicle has been observed past. The benchmark's
        ground truth for "did the preemption actually serve the vehicle
        that asked", which no counter inside the engine can answer --
        the engine only knows what it was told."""

    def __call__(self, now_s: float) -> None:
        live = set(traci.vehicle.getIDList())
        for vehicle_id in sorted(self._vehicle_ids & live):
            route = self._routes.get(vehicle_id)
            if route is None:
                route = self._routes[vehicle_id] = junctions_on_route(
                    tuple(traci.vehicle.getRoute(vehicle_id)), self._index
                )
            if not route:
                continue

            speed = traci.vehicle.getSpeed(vehicle_id)
            remaining: list[str] = []
            distances: dict[str, float] = {}
            movements: dict[str, str] = {}
            for junction_id, movement, approach_edge in route:
                # Negative means the vehicle is already past that edge, so
                # the junction drops off the route -- this is the geometric
                # release E3 prefers over a timeout, and it is why a
                # preemption here ends when the vehicle passes rather than
                # ten-plus seconds later the way cellular systems have been
                # measured doing.
                distance = traci.vehicle.getDrivingDistance(
                    vehicle_id, approach_edge, traci.lane.getLength(f"{approach_edge}_0")
                )
                if distance < 0.0:
                    continue
                remaining.append(junction_id)
                distances[junction_id] = distance
                movements[junction_id] = movement

            # Counted once per (vehicle, junction), not once per tick the
            # vehicle spends past it -- the first version incremented on
            # every observation, so a passage scored as high as the number
            # of remaining steps in the run.
            counted = self._counted.setdefault(vehicle_id, set())
            for junction_id in {j for j, _, _ in route} - set(remaining) - counted:
                counted.add(junction_id)
                self.passages[junction_id] = self.passages.get(junction_id, 0) + 1

            # An empty `remaining` is reported too, and that is the point
            # of this line rather than an oversight in it.
            #
            # The first version returned here, and the cost showed up in
            # the release-reason distribution: the *last* junction of
            # every response released as `stale_report` rather than
            # `passed` -- 41 of 281 releases over the recorded medium
            # gate, close to one per emergency vehicle per run. Nothing
            # unsafe happened; the bounded release is exactly what
            # catches a track that goes quiet. But the junction stayed
            # held for the full `report_ttl_s` after the vehicle had
            # already cleared it, and a reason that says "we lost the
            # vehicle" when the vehicle simply finished its route is the
            # release-reason distribution failing at its one job.
            #
            # A report with an empty route states the true thing: no
            # junctions remain ahead. `_Track.dropped_by_passing` reads
            # that as the whole previous route having left from the
            # front, which is a passage -- so the last junction releases
            # on geometry like every other one.
            self.observations += 1
            self._engine.submit(
                VehicleReport(
                    vehicle_id=vehicle_id,
                    observed_at_s=now_s,
                    route=tuple(remaining),
                    distance_to_m=distances,
                    speed_mps=speed,
                    movement_at=movements,
                    response_id=None,
                )
            )
