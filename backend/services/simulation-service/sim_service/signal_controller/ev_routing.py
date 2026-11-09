"""The live route function the dispatcher is injected with.

Lives here rather than in `control/dispatch/` for the reason every other
split in this project follows: anything that talks to TraCI stays in
this package, and the thing that reasons about the numbers stays a pure
module under `control/`. That is what lets `dispatcher.choose` be tested
against a dictionary of travel times instead of a simulator.
"""

from __future__ import annotations

import traci


def traci_route_fn(vtype: str = "veh_emergency"):
    """A `dispatch.RouteFn` backed by SUMO's own router.

    `traci.simulation.findRoute` routes against the network's *current*
    edge travel times, which is the whole reason dispatch is worth doing
    live: a facility further away down a clear road beats a nearer one
    behind the jam this corridor is currently producing, and only a
    router that sees the jam can tell them apart.

    Routed for the emergency vehicle type specifically. An emergency
    vClass is permitted on edges a passenger car is not, so routing the
    ambulance as a car would reject paths it is entitled to take and
    quietly return a worse facility -- a wrong answer rather than an
    error, which is the kind worth guarding against explicitly.

    Returns None where no path exists. A disconnected pair is a normal
    condition on a corridor extract whose edges stop at the bounding box,
    not an exceptional one, so it is a return value rather than a raise.
    """

    unknown: set[str] = set()

    def route(from_edge: str, to_edge: str) -> tuple[tuple[str, ...], float] | None:
        # The live corridor never loads `vtype` (its emergency vehicles use
        # SUMO's default type), and findRoute raises for an unknown type --
        # which used to read as "no hospital reachable" for every scene. So
        # an unknown type falls back to the default one rather than failing.
        for vt in dict.fromkeys((vtype, "")):
            if vt in unknown:
                continue
            try:
                result = traci.simulation.findRoute(from_edge, to_edge, vType=vt)
            except traci.TraCIException as exc:
                if "vehicle type" in str(exc):
                    unknown.add(vt)
                continue
            if not result.edges:
                return None
            return tuple(result.edges), float(result.travelTime)
        return None

    return route


def edge_latlon(edge_id: str) -> tuple[float, float]:
    """Where an edge starts, in the coordinates the facility register uses.

    `IncidentRequest` carries latitude and longitude because that is what
    a call for service has -- a dispatcher is given a location, not an
    edge id -- and the shortlist is computed against facility
    coordinates, which come from OSM. This is the one conversion between
    the two, and it goes through TraCI rather than through a second
    `sumolib.net.readNet` because the network is already open: reading it
    again costs seconds, and the benchmark does this on every one of a
    hundred and fifty runs.

    Takes the *start* of the edge rather than its centre. An incident is
    somewhere along a link and the difference is at most a link length,
    which is far below the error the air-distance shortlist already
    carries -- see `FacilityIndex.nearest_by_air` for why that shortlist
    is set generously instead of tightly."""
    shape = traci.lane.getShape(f"{edge_id}_0")
    x, y = shape[0]
    lon, lat = traci.simulation.convertGeo(x, y)
    return lat, lon
