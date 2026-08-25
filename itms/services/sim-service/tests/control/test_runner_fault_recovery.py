"""Unit test for `_recover_from_fault` -- the fix for a real gap the M4
bottleneck ablation surfaced (see the function's own docstring in
`runner.py`): once a junction hits `failsafe_interlock_rejected` (or
`failsafe_no_legal_plan`), `TraCICabinet`'s all-red state can never map
back to a known phase id, so without this recovery step the junction's
`JunctionContext` stays frozen forever and every subsequent tick fails
the same way. Uses `FakeCabinet` (the same fixture the C1-C5 fault-
injection tests use) rather than a real SUMO/TraCI connection -- this
function's own logic (command a phase, rebuild ctx) doesn't need one."""

from __future__ import annotations

from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.runner import _JunctionState, _recover_from_fault
from sim_service.signal_controller.cabinet import FakeCabinet


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

    assert js.ctx.has_demand == {}
    assert js.ctx.wait_times_s == {}
    assert js.ctx.queue_pcu == {}
