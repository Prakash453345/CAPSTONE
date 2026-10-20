"""Matching and the offer lifecycle, with no SUMO and no bus."""

from __future__ import annotations

import pytest
from itms_domain import EmergencyKind
from sim_service.live.crew_dispatch import (
    CrewDispatcher,
    CrewRoster,
    CrewUnit,
    units_from_accounts,
)


class FakeRoute:
    def __init__(self, eta_s: float) -> None:
        self.eta_s = eta_s


class FakePlanner:
    """ETAs from a table, so a test can state 'near by road' independently of
    'near on the map' -- which is the whole point of ranking by ETA."""

    def __init__(self, etas: dict[tuple[str, str], float]) -> None:
        self.etas = etas
        self.calls: list[tuple[str, str]] = []

    def plan(self, src: str, dst: str, _conditions):
        self.calls.append((src, dst))
        eta = self.etas.get((src, dst))
        if eta is None:
            from sim_service.routing.planner import NoRouteError

            raise NoRouteError(f"no route {src}->{dst}")
        return [FakeRoute(eta)]


class FakeGraph:
    edges: dict = {}


def roster(*units: CrewUnit) -> CrewRoster:
    return CrewRoster(units)


def amb(unit_id: str, edge: str, *, crew: str | None = "someone", on_duty=True, busy=False):
    return CrewUnit(
        unit_id=unit_id, kind=EmergencyKind.AMBULANCE, edge_id=edge,
        crew_username=crew, on_duty=on_duty, busy=busy,
    )


def make(units, etas, **kw):
    r = roster(*units)
    return r, CrewDispatcher(
        r, FakePlanner(etas), FakeGraph(), hex_index=None, prefilter_rings=None, **kw
    )


# ---- ranking ----------------------------------------------------------


def test_ranks_by_eta_not_by_distance():
    """The river case: B is nearer in a straight line, A is nearer by road."""
    r, d = make(
        [amb("EV-1", "north-bank"), amb("EV-2", "across-the-river")],
        {("north-bank", "incident"): 180.0, ("across-the-river", "incident"): 900.0},
    )
    assert [u for u, _ in d.rank(EmergencyKind.AMBULANCE, "incident")] == ["EV-1", "EV-2"]
    offer = d.request("inc-1", EmergencyKind.AMBULANCE, "incident", now_s=0.0)
    assert offer is not None and offer.unit_id == "EV-1" and offer.eta_s == 180.0


def test_only_the_kind_the_incident_needs():
    r, d = make(
        [
            amb("EV-1", "a"),
            CrewUnit("EV-9", EmergencyKind.POLICE, "b", crew_username="cop", on_duty=True),
        ],
        {("a", "inc"): 100.0, ("b", "inc"): 10.0},
    )
    # The police car is nearer, and irrelevant.
    assert [u for u, _ in d.rank(EmergencyKind.AMBULANCE, "inc")] == ["EV-1"]
    assert [u for u, _ in d.rank(EmergencyKind.POLICE, "inc")] == ["EV-9"]


def test_off_duty_busy_and_crewless_units_are_not_candidates():
    r, d = make(
        [
            amb("EV-off", "a", on_duty=False),
            amb("EV-busy", "b", busy=True),
            amb("EV-nobody", "c", crew=None),
            amb("EV-ok", "d"),
        ],
        {(x, "inc"): 60.0 for x in "abcd"},
    )
    assert [u for u, _ in d.rank(EmergencyKind.AMBULANCE, "inc")] == ["EV-ok"]


def test_unreachable_unit_is_dropped():
    r, d = make([amb("EV-1", "island"), amb("EV-2", "mainland")],
                {("mainland", "inc"): 300.0})
    assert [u for u, _ in d.rank(EmergencyKind.AMBULANCE, "inc")] == ["EV-2"]


def test_unit_already_on_the_incident_edge_is_instant():
    r, d = make([amb("EV-1", "inc")], {})
    assert d.rank(EmergencyKind.AMBULANCE, "inc") == [("EV-1", 0.0)]


def test_no_crew_of_that_kind_reports_exhausted():
    r, d = make([amb("EV-1", "a")], {("a", "inc"): 10.0})
    assert d.request("inc-1", EmergencyKind.FIRE_TRUCK, "inc", now_s=0.0) is None
    states = [e["payload"]["state"] for e in d.drain_events()]
    assert states == ["exhausted"]


# ---- offer lifecycle --------------------------------------------------


def test_accept_marks_busy_and_calls_back_once():
    r, d = make([amb("EV-1", "a")], {("a", "inc"): 120.0})
    accepted = []
    d.on_accept = accepted.append
    offer = d.request("inc-1", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    assert d.respond(offer.offer_id, accept=True, now_s=1.0).state == "accepted"
    assert r.get("EV-1").busy is True
    assert len(accepted) == 1
    # A second tap changes nothing and does not dispatch again.
    assert d.respond(offer.offer_id, accept=True, now_s=2.0) is None
    assert len(accepted) == 1


def test_a_crew_being_asked_about_one_call_is_not_asked_about_another():
    """Two incidents at once: the nearest crew is asked about the first, so
    the second goes to the next crew -- not to the same one, which would send
    one ambulance two places if it accepted both."""
    r, d = make(
        [amb("EV-1", "near"), amb("EV-2", "far")],
        {("near", "inc"): 100.0, ("far", "inc"): 400.0},
    )
    first = d.request("inc-1", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    second = d.request("inc-2", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    assert first.unit_id == "EV-1"
    assert second is not None and second.unit_id == "EV-2"


def test_decline_falls_through_to_the_next_nearest():
    r, d = make(
        [amb("EV-1", "near"), amb("EV-2", "far")],
        {("near", "inc"): 100.0, ("far", "inc"): 400.0},
    )
    first = d.request("inc-1", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    assert first.unit_id == "EV-1"
    second = d.respond(first.offer_id, accept=False, now_s=5.0)
    assert second is not None and second.unit_id == "EV-2"
    # Declining does not take the first crew out of service.
    assert r.get("EV-1").busy is False


def test_offer_expires_and_passes_to_the_next_crew():
    r, d = make(
        [amb("EV-1", "near"), amb("EV-2", "far")],
        {("near", "inc"): 100.0, ("far", "inc"): 400.0},
        offer_timeout_s=20.0,
    )
    first = d.request("inc-1", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    d.tick(now_s=10.0)
    assert first.state == "offered"      # not yet
    d.tick(now_s=20.1)
    assert first.state == "expired"
    assert d.open_offers[0].unit_id == "EV-2"


def test_everyone_declines_ends_in_exhausted():
    r, d = make([amb("EV-1", "a"), amb("EV-2", "b")],
                {("a", "inc"): 10.0, ("b", "inc"): 20.0})
    o = d.request("inc-1", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    o = d.respond(o.offer_id, accept=False, now_s=1.0)
    assert d.respond(o.offer_id, accept=False, now_s=2.0) is None
    assert [e["payload"]["state"] for e in d.drain_events()][-1] == "exhausted"


def test_a_crew_is_never_asked_twice_for_one_incident():
    r, d = make([amb("EV-1", "a"), amb("EV-2", "b")],
                {("a", "inc"): 10.0, ("b", "inc"): 20.0})
    o = d.request("inc-1", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    asked = [o.unit_id]
    o = d.respond(o.offer_id, accept=False, now_s=1.0)
    asked.append(o.unit_id)
    assert len(set(asked)) == 2


def test_unit_that_goes_off_duty_while_queued_is_skipped():
    r, d = make([amb("EV-1", "a"), amb("EV-2", "b")],
                {("a", "inc"): 10.0, ("b", "inc"): 20.0})
    o = d.request("inc-1", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    r.set_duty("EV-2", False)
    assert d.respond(o.offer_id, accept=False, now_s=1.0) is None   # nobody left


def test_withdraw_cancels_an_open_offer():
    r, d = make([amb("EV-1", "a")], {("a", "inc"): 10.0})
    o = d.request("inc-1", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    d.withdraw("inc-1", now_s=3.0)
    assert o.state == "withdrawn"
    assert d.respond(o.offer_id, accept=True, now_s=4.0) is None
    assert r.get("EV-1").busy is False


def test_release_puts_a_unit_back_in_the_pool():
    r, d = make([amb("EV-1", "a")], {("a", "inc"): 10.0})
    o = d.request("inc-1", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    d.respond(o.offer_id, accept=True, now_s=1.0)
    assert d.rank(EmergencyKind.AMBULANCE, "inc2") == []
    d.release("EV-1")
    assert r.get("EV-1").available is True


# ---- roster -----------------------------------------------------------


def test_roster_refresh_keeps_live_position_and_busy_state():
    r = roster(amb("EV-1", "where-it-is"))
    r.set_busy("EV-1", True)
    r.upsert(amb("EV-1", "stale-depot"))        # an account refresh
    assert r.get("EV-1").edge_id == "where-it-is"
    assert r.get("EV-1").busy is True


def test_accounts_without_a_unit_or_kind_are_not_vehicles():
    units = units_from_accounts([
        {"username": "komal", "crew_kind": None, "unit_id": None},        # operator
        {"username": "half", "crew_kind": "ambulance", "unit_id": ""},    # no vehicle
        {"username": "weird", "crew_kind": "spaceship", "unit_id": "X1"},  # bad kind
        {"username": "amb12", "crew_kind": "ambulance", "unit_id": "EV-001",
         "on_duty": True, "edge_id": "depot-a"},
    ])
    assert [u.unit_id for u in units] == ["EV-001"]
    assert units[0].kind is EmergencyKind.AMBULANCE and units[0].crew_username == "amb12"


def test_for_crew_finds_the_signed_in_drivers_vehicle():
    r = roster(amb("EV-1", "a", crew="amb12"), amb("EV-2", "b", crew="amb27"))
    assert r.for_crew("amb27").unit_id == "EV-2"
    assert r.for_crew("nobody") is None


# ---- hex prefilter ----------------------------------------------------


class FakeHex:
    """edge -> cells, with cells as (q, r) so `disk` maths applies."""

    def __init__(self, mapping):
        self.edge_cells = mapping


def test_hex_prefilter_narrows_candidates_but_never_hides_the_only_crew():
    units = [amb("EV-near", "near"), amb("EV-far", "far")]
    etas = {("near", "inc"): 100.0, ("far", "inc"): 200.0}
    r = CrewRoster(units)
    hexed = FakeHex({"inc": ((0, 0),), "near": ((1, 0),), "far": ((99, 99),)})
    d = CrewDispatcher(r, FakePlanner(etas), FakeGraph(), hex_index=hexed, prefilter_rings=2)
    # EV-far is outside the ring, so it is never planned for.
    assert [u for u, _ in d.rank(EmergencyKind.AMBULANCE, "inc")] == ["EV-near"]
    assert ("far", "inc") not in d.planner.calls

    # ... but if the only crew is far away, the prefilter must not hide them.
    r2 = CrewRoster([amb("EV-far", "far")])
    d2 = CrewDispatcher(r2, FakePlanner(etas), FakeGraph(), hex_index=hexed, prefilter_rings=2)
    assert [u for u, _ in d2.rank(EmergencyKind.AMBULANCE, "inc")] == ["EV-far"]


def test_max_planned_caps_the_planner_work():
    units = [amb(f"EV-{i}", f"e{i}") for i in range(20)]
    etas = {(f"e{i}", "inc"): float(i) for i in range(20)}
    r = CrewRoster(units)
    d = CrewDispatcher(r, FakePlanner(etas), FakeGraph(), hex_index=None,
                       prefilter_rings=None, max_planned=5)
    d.rank(EmergencyKind.AMBULANCE, "inc")
    assert len(d.planner.calls) <= 5


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_auto_accept_assigns_the_nearest_crew_without_waiting():
    """The simulation default: nobody has to tap Accept for a unit to move."""
    r, d = make(
        [amb("EV-1", "near"), amb("EV-2", "far")],
        {("near", "inc"): 100.0, ("far", "inc"): 400.0},
        auto_accept=True,
    )
    accepted = []
    d.on_accept = accepted.append
    offer = d.request("inc-1", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    assert offer is not None and offer.state == "accepted" and offer.unit_id == "EV-1"
    assert [o.unit_id for o in accepted] == ["EV-1"]
    assert r.get("EV-1").busy is True
    # the next call goes to the next free crew, also at once
    second = d.request("inc-2", EmergencyKind.AMBULANCE, "inc", now_s=0.0)
    assert second.unit_id == "EV-2" and second.state == "accepted"
