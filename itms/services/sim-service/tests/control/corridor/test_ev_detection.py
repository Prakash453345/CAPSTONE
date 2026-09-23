"""Route reading: turning an emergency vehicle's edge list into the
junctions and movements the corridor engine can act on.

Runs against the real corridor's extracted configuration rather than a
synthetic one, because the thing being tested is a property of *this*
network's connection table -- how many of its 73 movements are uniquely
identifiable from a route -- and a hand-built two-phase junction cannot
have that property at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sim_service.control.corridor.junction import protected_phase_for
from sim_service.signal_controller.ev_detection import (
    build_movement_index,
    junctions_on_route,
)

_ROOT = Path(__file__).resolve().parents[5]
_NET = _ROOT / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"

# The arterial through every signal-controlled junction, taken from the
# demand file's own most-used route.
_ARTERIAL = (
    "219187869 350502993#0 350502993#1 350502993#2 350502993#4 "
    "350502993#6 350502993#7 -343269496 220332271#0"
).split()


@pytest.fixture(scope="module")
def corridor():
    if not _NET.exists():  # pragma: no cover - network artefact absent
        pytest.skip("corridor network artefact not present")
    sys.path.insert(0, str(_NET.parent))
    from extract_tier0_config import load_configs
    from link_lanes import link_to_lane_map, link_to_receiving_lane_map

    configs = load_configs(str(_NET))
    index = build_movement_index(
        link_to_lane_map(str(_NET)), link_to_receiving_lane_map(str(_NET)), configs
    )
    return configs, index


def test_the_arterial_route_resolves_at_every_junction(corridor):
    """The measurement that forced `build_movement_index`'s resolution
    rule. Dropping every ambiguous edge pair -- as the first version did,
    on the reasonable-sounding principle of never guessing -- left the
    arterial through all seven junctions resolving to exactly one of
    them, so the corridor engine could preempt at one junction out of
    seven and the whole route-level design was inert.

    The ambiguity is mundane: a three-lane through manoeuvre is three
    links in SUMO's connection table. They share a protected phase, so
    the question "which phase does this vehicle need" has one answer even
    though "which link" has three."""
    configs, index = corridor
    hits = junctions_on_route(tuple(_ARTERIAL), index)
    assert len(hits) == len(configs), (
        f"arterial resolves at {len(hits)} of {len(configs)} junctions"
    )
    assert len({j for j, _, _ in hits}) == len(configs), "a junction resolved twice"


def test_every_indexed_movement_has_a_protected_phase(corridor):
    """A5/D3, at the index rather than at the junction. If a route could
    resolve to a permissively-served movement, the engine would look up
    its protected phase, find none, and defer -- correct but wasteful.
    Resolving by protected phase in the first place means an indexed
    movement always has one."""
    configs, index = corridor
    for junction_id, movement in index.values():
        assert protected_phase_for(configs[junction_id], movement) is not None


def test_route_order_is_traversal_order(corridor):
    """The engine's release rule depends on it: junctions leave a
    vehicle's route from the front as it drives past them, and a junction
    that disappears from anywhere else left because the route changed.
    Those are opposite outcomes -- the preemption worked, or it was spent
    on a vehicle that went elsewhere -- and telling them apart is what
    makes the release-reason distribution readable."""
    _, index = corridor
    hits = junctions_on_route(tuple(_ARTERIAL), index)
    approach_positions = [_ARTERIAL.index(edge) for _, _, edge in hits]
    assert approach_positions == sorted(approach_positions)


def test_a_route_that_touches_no_controlled_junction_resolves_to_nothing(corridor):
    _, index = corridor
    assert junctions_on_route(("no_such_edge", "also_not_real"), index) == []
    assert junctions_on_route((), index) == []
