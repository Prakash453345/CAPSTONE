"""Preemption must hand an emergency vehicle a *protected* green.

Commit `626e45e` changed `CorridorController._phase_serving` to count
`protected_movements` instead of `green_movements`, and shipped without
tests of its own -- the project's own verification run said so:

    "Side effect: if a junction has *no* phase protecting the EV's
     movement, it now returns no preemption there (safer, but no corridor
     at that junction). No unit test was added for this."

and separately, of the benchmark:

    "the min-green hold path and the green-corridor change are never
     triggered in these scenarios (they need emergency preemption)."

So the change is correct, uncovered, and unexercised. These are the tests.

**Why it matters, in one sentence.** SUMO's `'g'` is a permissive green:
the movement may proceed *only after yielding*. Handing that to a
preempted emergency vehicle tells the crew they hold the junction when
they have been told to give way -- hazards D3 and A5, and the same
`'G'`/`'g'` confusion that produced a measured 5 junction collisions
across 3 seeds when `TraCICabinet` made the mirror-image mistake in M7.

Four of this corridor's seven junctions carry permissive movements, so
this is a live distinction on the real network, not a theoretical one.
"""

from __future__ import annotations

import logging

from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.live.green_corridor import CorridorController

_PROTECTED = "mEV"
_PERMISSIVE = "mYield"


def _cfg(*, protected_phase: bool = True) -> Tier0Config:
    """Two phases. P0 serves the EV movement *permissively* (it is green
    but must yield); P1 serves it *protected* -- unless `protected_phase`
    is False, in which case nothing protects it anywhere and the corridor
    has no legal phase to preempt onto."""
    p1_protected = frozenset({_PROTECTED}) if protected_phase else frozenset()
    return Tier0Config(
        intersection_id="J",
        phases={
            "P0": Phase(
                "P0",
                green_movements=frozenset({_PROTECTED, _PERMISSIVE}),
                protected_movements=frozenset({_PERMISSIVE}),
            ),
            "P1": Phase(
                "P1",
                green_movements=frozenset({_PROTECTED}),
                protected_movements=p1_protected,
            ),
        },
        ring_order=("P0", "P1"),
        conflict_matrix={
            _PROTECTED: frozenset({_PERMISSIVE}),
            _PERMISSIVE: frozenset({_PROTECTED}),
        },
        min_green_s={"P0": 10.0, "P1": 10.0},
        max_green_s={"P0": 40.0, "P1": 40.0},
        yellow_s=3.0,
        all_red_s=2.0,
        sat_flow_pcu_s={_PROTECTED: 1.0, _PERMISSIVE: 1.0},
    )


def _serving(cfg: Tier0Config, wanted: set[str], prefer: str = "P0") -> str | None:
    return CorridorController._phase_serving(cfg, frozenset(wanted), prefer=prefer)


# -- the fix itself ----------------------------------------------------


def test_a_permissive_green_does_not_count_as_serving_the_movement():
    """The defect `626e45e` closed. P0 is green for the EV movement and
    would have been chosen by the old code, which counted
    `green_movements`; it only permits the movement subject to yielding,
    so it must not be what a preemption selects."""
    cfg = _cfg()
    assert _serving(cfg, {_PROTECTED}) == "P1"
    # ...and the old rule really would have picked the other one, so the
    # test is discriminating rather than merely passing.
    old_choice = max(
        cfg.ring_order, key=lambda p: len(cfg.phases[p].green_movements & {_PROTECTED})
    )
    assert old_choice == "P0"


def test_no_protected_phase_means_no_preemption_rather_than_a_permissive_one():
    """The side effect the verification flagged and nobody tested. When
    nothing protects the movement the honest answer is None -- refusing
    to preempt -- not falling back to the permissive phase."""
    assert _serving(_cfg(protected_phase=False), {_PROTECTED}) is None


def _one_phase(protected: frozenset[str] | None) -> Tier0Config:
    return Tier0Config(
        intersection_id="J",
        phases={
            "P0": Phase(
                "P0", green_movements=frozenset({_PROTECTED}), protected_movements=protected
            )
        },
        ring_order=("P0",),
        conflict_matrix={_PROTECTED: frozenset()},
        min_green_s={"P0": 10.0},
        max_green_s={"P0": 40.0},
        yellow_s=3.0,
        all_red_s=2.0,
        sat_flow_pcu_s={_PROTECTED: 1.0},
    )


def test_omitted_and_empty_protected_sets_mean_opposite_things():
    """The distinction the `if not None` idiom exists to preserve, and the
    one an `or` would destroy.

    *Omitted* means "this junction never recorded the distinction" --
    every hand-built and synthetic config -- and `Phase.__post_init__`
    normalises it to the full green set, so the phase serves the movement.
    *Explicitly empty* means "nothing here is protected" and is preserved
    verbatim, so it must not.

    Worth noting where that leaves the guard inside `_phase_serving`:
    because `__post_init__` normalises at construction, the
    `protected_movements is not None` branch can never take its else path
    on a real `Phase`. It is unreachable defensive code rather than live
    logic. Harmless, and left alone deliberately -- it is the correct
    shape if that normalisation ever moves -- but it is not what makes
    the empty case work. `__post_init__` is."""
    omitted = _one_phase(None)
    assert omitted.phases["P0"].protected_movements == frozenset({_PROTECTED}), (
        "Phase.__post_init__ normalises an omitted protected set to green_movements"
    )
    assert _serving(omitted, {_PROTECTED}) == "P0"

    empty = _one_phase(frozenset())
    assert empty.phases["P0"].protected_movements == frozenset(), "empty is preserved"
    assert _serving(empty, {_PROTECTED}) is None, (
        "an empty protected set means nothing is protected, not 'use the green set'"
    )


def test_prefer_only_breaks_ties_among_phases_that_actually_protect():
    """`prefer` exists so the corridor does not switch needlessly. It must
    not be able to keep a permissive phase live just because it is the one
    already running -- that would reintroduce the defect through the
    tie-break instead of through the overlap count."""
    cfg = _cfg()
    assert _serving(cfg, {_PROTECTED}, prefer="P0") == "P1"
    assert _serving(cfg, {_PROTECTED}, prefer="P1") == "P1"


# -- the silence, which was the other half of the problem --------------


def _controller() -> CorridorController:
    return CorridorController.__new__(CorridorController)  # no graph needed


def test_an_unprotected_junction_is_counted_and_warned_not_silently_skipped(caplog):
    """`preemption_plan` returning None is indistinguishable at the
    arbiter from "no corridor is active here". A corridor can therefore
    report itself ACTIVE while one of its junctions is never preempted.
    `activate` already logs the route-level version of this; this pins the
    per-junction one."""
    controller = _controller()
    controller.unprotected_junctions = {}
    controller._warned_unprotected = set()
    cfg = _cfg(protected_phase=False)
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=20.0
    )

    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            assert controller._report_unprotected(cfg, frozenset({_PROTECTED})) is None

    assert controller.unprotected_junctions == {"J": 5}, "every tick must be counted"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1, (
        "one line per junction, not one per tick -- preemption_plan runs every tick "
        f"the window is open, got {len(warnings)}"
    )
    assert "J" in warnings[0].getMessage()
    assert ctx.current_phase_id == "P0"  # nothing was commanded


# -- shared approach lane (12 Nov 2026) -----------------------------------


def _shared_lane_cfg() -> Tier0Config:
    """Junction 2833253632 in miniature: the EV's turn `t` is protected in
    both P0 (side street `x` + `t`) and P1 (`t` + the straight `s` from the
    EV's own lane)."""
    both = frozenset({"t"})
    return Tier0Config(
        intersection_id="J",
        phases={
            "P0": Phase("P0", green_movements=both | {"x"}, protected_movements=both | {"x"}),
            "P1": Phase("P1", green_movements=both | {"s"}, protected_movements=both | {"s"}),
        },
        ring_order=("P0", "P1"),
        conflict_matrix={"x": frozenset({"s"}), "s": frozenset({"x"}), "t": frozenset()},
        min_green_s={"P0": 10.0, "P1": 10.0},
        max_green_s={"P0": 40.0, "P1": 40.0},
        yellow_s=3.0,
        all_red_s=2.0,
        sat_flow_pcu_s={"x": 1.0, "s": 1.0, "t": 1.0},
    )


def test_the_phase_that_clears_the_evs_whole_lane_wins_a_tie():
    cfg = _shared_lane_cfg()
    # without lane information: the live phase wins the tie, as before
    assert CorridorController._phase_serving(cfg, frozenset({"t"}), prefer="P0") == "P0"
    # with it: P1, which also greens the straight `s` leaving the EV's lane,
    # even though P0 is live
    assert CorridorController._phase_serving(
        cfg, frozenset({"t"}), prefer="P0", lane_mates=frozenset({"s"})
    ) == "P1"


def test_lane_mates_never_outrank_protection():
    """A phase that greens the whole lane but protects less of what the EV
    needs must still lose to one that protects more of it."""
    cfg = _shared_lane_cfg()
    # the EV needs t and x; P0 protects both, P1 protects only t (but greens s)
    assert CorridorController._phase_serving(
        cfg, frozenset({"t", "x"}), prefer="P1", lane_mates=frozenset({"s"})
    ) == "P0"


def test_road_graph_records_links_that_share_an_approach_lane():
    from sim_service.routing import RoadGraph
    from itms_domain.paths import DATA_DIR

    net = DATA_DIR / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
    if not net.exists():
        import pytest
        pytest.skip("corridor network not present")
    g = RoadGraph.from_network(net)
    assert g.link_lane_mates["2833253632"]["L2"] == frozenset({"L3"})
    assert g.link_lane_mates["2833253632"]["L4"] == frozenset()


def test_preemption_switches_for_the_lane_only_when_a_lane_mate_is_queued():
    """`preemption_plan` wiring: the lane preference applies only when a car
    is queued on a movement sharing the EV's lane. Otherwise the live phase,
    which already protects the EV, is kept."""
    from types import SimpleNamespace

    cfg = _shared_lane_cfg()
    ctl = CorridorController.__new__(CorridorController)
    ctl.graph = SimpleNamespace(link_lane_mates={"J": {"t": frozenset({"s"}), "s": frozenset({"t"})}})
    ctl.unprotected_junctions = {}
    ctl._warned_unprotected = set()
    ctl._open_reservation = lambda tl: SimpleNamespace(movements=("t",))

    def target(queue):
        ctx = JunctionContext(intersection_id="J", current_phase_id="P0",
                              current_phase_elapsed_s=30.0, queue_pcu=queue)
        plan = CorridorController.preemption_plan(ctl, cfg, ctx, tick_s=1.0)
        return plan.steps[-1].phase_id

    assert target({}) == "P0"            # nobody on the lane: keep the live phase
    assert target({"s": 2.0}) == "P1"    # a straight car queued: clear the lane
