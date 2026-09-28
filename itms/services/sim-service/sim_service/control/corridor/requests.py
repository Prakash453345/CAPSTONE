"""What a preemption requester asserts, and what the engine derives from it.

The split between the two is the design's answer to hazard E10, and it is
worth stating before the types, because getting it backwards is what makes
route-based ("green corridor") preemption *more* dangerous than the
per-junction kind it improves on.

Conventional point-detection EVP cannot hold a signal for a vehicle that
has stopped, because it never commits ahead: the call exists only while
the vehicle is in range. A corridor system commits to junctions the
vehicle has not reached yet, so it inherits a failure the older design is
structurally immune to -- an ETA that has quietly expired while a whole
corridor is held for it. WSDOT names the converse limitation of the
legacy design in the same breath ("point detection systems cannot
recognize speed changes or stops before intersection arrival"), and the
pair of limitations is the real tradeoff: reacting late, or committing to
a prediction.

So a requester here asserts only what it can observe -- identity, class,
position, speed, intended movement, and when it observed them. It never
asserts an ETA. `CorridorEngine` derives arrival times itself, from the
freshest report it holds, and every derived quantity carries the age of
the report it came from. A track whose reports stop arriving goes stale
and its reservations are released; it does not coast on its last ETA.

**Untrusted input.** Every field below arrives from outside the safety
kernel and is treated as adversarial, per E13: homemade infrared
transmitters reproducing a vendor's pulse protocol are a documented,
demonstrated attack (an Arduino and an LED array), and the legal
deterrent that exists -- SAFETEA, August 2005 -- is deterrence, not
prevention. `PreemptionClass` is therefore not taken from the request
wire format; it is looked up from `vehicle_id` in an authorization table
the engine is constructed with, so an unknown id cannot assert that it is
a fire engine. That is the software half of MUTCD 11th Ed.'s guidance
that EVP equipment "should encode vehicle IDs"; the cryptographic half
belongs to the detection channel and is out of scope for a simulator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum


class PreemptionClass(IntEnum):
    """Total order over requester classes -- **lower value wins**.

    The order is MUTCD 11th Ed. §4F.18's Guidance list (train -> boat ->
    heavy vehicle -> light vehicle -> light rail -> rubber-tired transit),
    and its rationale is worth keeping attached to it because it is not
    the one people assume: the ordering is by **controllability, not
    urgency**. "A vehicle that is more difficult to control supersedes"
    one that is easier. A train cannot stop; a fire appliance stops badly;
    a police car stops well. Nothing in the ordering claims a police
    emergency is less urgent than a fire.

    Gaps of 10 are deliberate. Agencies routinely need to place a local
    class between two of these (D8: MUTCD lumps fire and ambulance
    together as "heavy vehicle", and NCHRP Synthesis 507 found 71% of
    agencies prioritize preempts at all, 12% do not and 17% are unsure --
    so fire-versus-ambulance is decided locally or not at all), and an
    enum with no room forces that decision into a tie-break where it is
    invisible.

    **The direction of this ordering is the thing to distrust.** D7 in the
    hazard catalogue is that the sources contradict each other: the NEMA
    TS2 specification says "low-numbered priority preemptors shall
    override higher-numbered priority preemptor calls", and Florida LTAP's
    *Traffic Signal Timing 201* says "higher-numbered inputs always
    override lower-numbered ones". A designer who assumes the wrong one
    inverts the entire safety hierarchy -- transit above fire. ITS
    lessons-learned records that exact failure reaching deployment
    ("traffic signal software can inadvertently grant transit priority
    requests equal precedence to emergency preemption"). The mitigation in
    the literature is to bench-test every pairwise combination rather than
    trust any document, including this docstring;
    `tests/control/test_corridor_arbitration.py::test_every_class_pair`
    is that bench test, enumerating all pairs and asserting the winner of
    each.
    """

    RAIL = 0
    FIRE = 10
    AMBULANCE = 20
    POLICE = 30
    LIGHT_RAIL = 80
    TRANSIT = 90


@dataclass(frozen=True)
class VehicleReport:
    """One observation of one emergency vehicle, from a detector, an
    on-board GPS/CV message, or (in simulation) TraCI.

    Carries no ETA and no reservation -- see the module docstring. It is a
    measurement, timestamped, and the engine decides what it means.

    `route` is the vehicle's *remaining* junctions in traversal order,
    nearest first. A vehicle that turns off the corridor reports a shorter
    route on its next observation, and the junctions that dropped off it
    are released on that tick rather than held to a timeout -- which is
    hazard G4 ("preemption of intersections the EV never traverses":
    pure cost, no benefit, and the place public tolerance for EVP is
    spent).

    `movement_at` names which movement the vehicle will use at each
    junction, not merely which approach. D3 is why: two units on the same
    approach, one going through and one turning left across the opposing
    through, are served by the same approach and *not* by the same
    protected path. An approach-level request would hand the turning unit
    a green and a confirmation indication for a movement nothing has
    cleared.

    `confidence` is the detection channel's own estimate, in [0, 1], and
    is the hook for E14 (GPS in urban canyons: "dense buildings prevent
    signal reception", exactly where junctions are densest) and E11/E4
    (optical dropout from a truck, a curve, heavy rain, direct sun). The
    engine treats a low-confidence report as a reason to shorten its
    commitment horizon, never as a reason to refuse a request outright:
    degraded detection is the normal condition of a real corridor, and a
    system that only works on clean data does not work.
    """

    vehicle_id: str
    observed_at_s: float
    route: tuple[str, ...]
    distance_to_m: Mapping[str, float]
    speed_mps: float
    movement_at: Mapping[str, str] = field(default_factory=dict)
    confidence: float = 1.0
    response_id: str | None = None
    """Which incident this vehicle is responding to, when dispatch knows.

    Exists for G5: a multi-alarm response puts several units on the same
    or converging routes over a few minutes, and handled as N independent
    requests that is N sequential preemptions with no recovery between
    them (F8), which is how a corridor spends an entire peak period in
    transition -- a state, as the catalogue notes, that nobody times or
    optimises for. Units sharing a `response_id` are coalesced into one
    reservation per junction, held until the last of them passes, so the
    corridor pays one interruption instead of N.

    `None` means unknown, and unknown is treated as "its own response"
    rather than "same as everything else": merging two genuinely separate
    emergencies would hold a junction for a vehicle that is not coming."""

    def __post_init__(self) -> None:
        if self.speed_mps < 0.0:
            raise ValueError(f"speed_mps must be >= 0, got {self.speed_mps}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")


@dataclass(frozen=True)
class Reservation:
    """The engine's commitment to one vehicle at one junction.

    This is the object the arbitration ladder's rung 3 exists to service
    (`signal_controller/arbiter.py`'s docstring: "3. Green corridor
    preemption"), and `camp.py`'s own docstring anticipated it -- "the
    Green Corridor Engine exists to publish real `Reservation`s".

    A reservation is *not* a command. It says a junction is claimed, by
    whom, for which movement, and until when. Whether the junction can
    actually serve it on this tick is decided by the per-junction state
    machine against the interlocks, and the answer is frequently no --
    which is the honest shape of the thing. FHWA's doctrine for crews is
    "a green light is not guaranteed", and a data structure that implied
    otherwise would be lying to the part of the system that computes the
    confirmation indication.
    """

    vehicle_id: str
    junction_id: str
    priority: PreemptionClass
    movement: str
    granted_at_s: float
    expires_at_s: float
    """Hard upper bound on the commitment, always finite.

    F9 in the catalogue is an indefinitely-held preemption, and it is the
    failure with the widest blast radius in the whole EVP literature: FHWA
    states plainly that when an emergency vehicle stops near an
    intersection with a running emitter it "will hold the signal in the
    preemption phase indefinitely, causing significant traffic problems"
    -- at an incident scene, which is precisely when the surrounding
    network most needs to keep working. Fairfax County and Plano each had
    to build custom emitter power-interrupt hardware because the
    controller side had no bound. Making the bound a required, non-
    optional field of the commitment itself is cheaper than any of that,
    and it cannot be forgotten during configuration."""

    def active_at(self, now_s: float) -> bool:
        return self.granted_at_s <= now_s < self.expires_at_s
