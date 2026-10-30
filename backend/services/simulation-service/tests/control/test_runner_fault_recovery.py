"""Unit test for `_recover_from_fault` -- the fix for a real gap the M4
bottleneck ablation surfaced (see the function's own docstring in
`runner.py`): once a junction hits `failsafe_interlock_rejected` (or
`failsafe_no_legal_plan`), `TraCICabinet`'s all-red state can never map
back to a known phase id, so without this recovery step the junction's
`JunctionContext` stays frozen forever and every subsequent tick fails
the same way. Uses `FakeCabinet` (the same fixture the C1-C5 fault-
injection tests use) rather than a real SUMO/TraCI connection -- this
function's own logic (command a phase, rebuild ctx) doesn't need one.

**Updated when recovery was made to run through the normal clearance
sequence.** The original assertions here checked that the recovery green
was commanded *immediately* -- which, combined with the arbiter's
snap-to-red in the same tick, meant the junction physically jumped from
one green straight to a conflicting green. Recovery now shows the
outgoing phase's yellow, then all-red, then the recovery green, so these
tests drive that transition to completion (`_settle`) before asserting
which phase the junction landed in. Where the recovery phase equals the
phase that was already green there is nothing to clear and the command
is still immediate. See `test_runner_decision_contract.py` for the
tick-by-tick display-sequence assertions."""

from __future__ import annotations

from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.runner import (
    _advance_transition,
    _JunctionState,
    _recover_from_fault,
)
from sim_service.signal_controller.cabinet import FakeCabinet


def _settle(js: _JunctionState) -> None:
    """Run any clearance transition recovery scheduled through to its
    green, exactly as the runner's main loop would over the next ticks."""
    for _ in range(100):
        if js.transition is None:
            return
        _advance_transition(js, 1.0)
    raise AssertionError("recovery transition never completed")


def _cfg() -> Tier0Config:
    phases = {
        "P0": Phase("P0", frozenset({"L0"})),
        "P1": Phase("P1", frozenset({"L1"})),
    }
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=("P0", "P1"),
        conflict_matrix={"L0": frozenset(), "L1": frozenset()},
        min_green_s={"P0": 10.0, "P1": 10.0},
        max_green_s={"P0": 30.0, "P1": 30.0},
        yellow_s=3.0,
        all_red_s=2.0,
    )


def test_recover_from_fault_commands_the_rings_first_phase():
    cfg = _cfg()
    cabinet = FakeCabinet()
    cabinet.command_all_red()  # simulate the failsafe branch that just ran
    stale_ctx = JunctionContext(
        intersection_id="J", current_phase_id="P1", current_phase_elapsed_s=987.0
    )
    js = _JunctionState(cfg=cfg, cabinet=cabinet, ctx=stale_ctx)

    _recover_from_fault(js, "J")
    _settle(js)

    assert cabinet.read_state().phase_id == "P0"  # the command actually landed
    assert js.ctx.current_phase_id == "P0"
    assert js.ctx.current_phase_elapsed_s == 0.0
    assert js.ctx.intersection_id == "J"


def test_recover_from_fault_clears_stale_demand_and_queue_fields():
    # A frozen ctx doesn't just carry a stale phase/elapsed -- confirm the
    # rebuilt ctx doesn't drag forward stale has_demand/wait_times_s/
    # queue_pcu either (the next tick's detector/queue_sampler refreshes
    # them for real; this function shouldn't pretend to know their values).
    cfg = _cfg()
    cabinet = FakeCabinet()
    stale_ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P1",
        current_phase_elapsed_s=500.0,
        has_demand={"L0": True},
        wait_times_s={"L0": 999.0},
        queue_pcu={"L0": 42.0},
    )
    js = _JunctionState(cfg=cfg, cabinet=cabinet, ctx=stale_ctx)

    _recover_from_fault(js, "J")
    _settle(js)

    assert js.ctx.has_demand == {}
    assert js.ctx.wait_times_s == {}
    assert js.ctx.queue_pcu == {}


def test_recover_from_fault_routes_to_the_phase_that_serves_the_violated_movement():
    # The fix for the gap this function's own docstring now describes in
    # its second half (PROGRESS.md's "Real saturation-flow calibration"
    # finding): resetting to ring_order[0] unconditionally, regardless of
    # which movement an I5 rejection actually named, can strand recovery on
    # a phase that doesn't serve that movement either -- the same rejection
    # then fires again next tick, forever. Given violated_movements, resume
    # into whichever phase actually serves one instead.
    cfg = _cfg()
    cabinet = FakeCabinet()
    stale_ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=452.0
    )
    js = _JunctionState(cfg=cfg, cabinet=cabinet, ctx=stale_ctx)

    _recover_from_fault(js, "J", frozenset({"L1"}))
    _settle(js)

    assert cabinet.read_state().phase_id == "P1"
    assert js.ctx.current_phase_id == "P1"
    assert js.ctx.current_phase_elapsed_s == 0.0


def test_recover_from_fault_falls_back_to_rings_first_phase_when_no_phase_serves_it():
    # A violation naming a movement no live phase actually serves (or an
    # empty violated_movements, every non-I5 fault mode's default) must
    # still resolve to *something* -- ring_order[0], exactly as before this
    # fix, rather than raising or leaving the junction uncommanded.
    cfg = _cfg()
    cabinet = FakeCabinet()
    stale_ctx = JunctionContext(
        intersection_id="J", current_phase_id="P1", current_phase_elapsed_s=10.0
    )
    js = _JunctionState(cfg=cfg, cabinet=cabinet, ctx=stale_ctx)

    _recover_from_fault(js, "J", frozenset({"L99_no_such_movement"}))
    _settle(js)

    assert cabinet.read_state().phase_id == "P0"
    assert js.ctx.current_phase_id == "P0"


def test_recover_from_fault_defaults_to_rings_first_phase_with_no_violated_movements():
    cfg = _cfg()
    cabinet = FakeCabinet()
    cabinet.command_all_red()
    stale_ctx = JunctionContext(
        intersection_id="J", current_phase_id="P1", current_phase_elapsed_s=987.0
    )
    js = _JunctionState(cfg=cfg, cabinet=cabinet, ctx=stale_ctx)

    _recover_from_fault(js, "J")  # no third arg -- exercises the default
    _settle(js)

    assert js.ctx.current_phase_id == "P0"
