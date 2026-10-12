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
