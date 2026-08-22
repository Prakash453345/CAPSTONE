"""C1-C5 [build guide §5.C] against the arbiter + a `FakeCabinet`: the M2
gate's other half (property tests cover "can't produce a conflicting
green"; this covers "faults reach a defined safe state"). Each test
injects exactly the fault its case describes and asserts the arbiter's
documented response -- degrade, alarm, never fight the hardware, never
resume into an assumed phase.
"""

from __future__ import annotations

from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.signal_controller import arbiter
from sim_service.signal_controller.cabinet import FakeCabinet


def _cfg(**overrides) -> Tier0Config:
    defaults = dict(
        intersection_id="J",
        phases={
            "NS": Phase("NS", frozenset({"N", "S"})),
            "EW": Phase("EW", frozenset({"E", "W"})),
        },
        ring_order=("NS", "EW"),
        conflict_matrix={
            "N": frozenset({"E", "W"}),
            "S": frozenset({"E", "W"}),
            "E": frozenset({"N", "S"}),
            "W": frozenset({"N", "S"}),
        },
        min_green_s={"NS": 10.0, "EW": 10.0},
        max_green_s={"NS": 10.0, "EW": 10.0},
        yellow_s=3.0,
        all_red_s=2.0,
    )
    defaults.update(overrides)
    return Tier0Config(**defaults)


def test_baseline_tick_commands_a_plan_on_a_healthy_cabinet():
    cfg = _cfg()
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=0.0)
    cabinet = FakeCabinet()

    decision = arbiter.tick(cfg, ctx, cabinet)

    assert decision.mode == "fixed_time"
    assert decision.plan is not None
    assert decision.events and decision.events[0]["phase_id"] == "NS"
    assert cabinet.read_state().phase_id == "NS"


def test_C1_lamp_failure_routes_around_the_faulted_phase():
    cfg = _cfg()
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="EW",
        current_phase_elapsed_s=0.0,
        faulted_phases=frozenset({"NS"}),
    )
    cabinet = FakeCabinet()

    decision = arbiter.tick(cfg, ctx, cabinet)

    assert decision.mode == "fixed_time"
    assert decision.plan is not None
    assert all(step.phase_id != "NS" for step in decision.plan.steps)


def test_C1_every_phase_faulted_drops_to_failsafe():
    cfg = _cfg()
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="NS",
        current_phase_elapsed_s=0.0,
        faulted_phases=frozenset({"NS", "EW"}),
    )
    cabinet = FakeCabinet()

    decision = arbiter.tick(cfg, ctx, cabinet)

    assert decision.mode == "failsafe_no_legal_plan"
    assert decision.plan is None
    assert cabinet.read_state().phase_id is None  # commanded to all-red, not left commanding NS


def test_C2_conflict_monitor_trip_is_observed_not_fought():
    cfg = _cfg()
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=5.0)
    cabinet = FakeCabinet()
    cabinet.command("NS")
    cabinet.trip_conflict_monitor()

    decision = arbiter.tick(cfg, ctx, cabinet)

    assert decision.mode == "failsafe_hardware_override"
    assert decision.plan is None
    # The arbiter must not have tried to command over the trip.
    assert cabinet.read_state().hardware_override is True


def test_C3_comms_loss_stops_commanding():
    cfg = _cfg()
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=5.0)
    cabinet = FakeCabinet()
    cabinet.command("NS")
    cabinet.drop_comms()

    decision = arbiter.tick(cfg, ctx, cabinet)

    assert decision.mode == "degraded_comms_lost"
    assert decision.plan is None


def test_C3_comms_loss_on_the_command_side_is_also_caught():
    """Comms can drop between the read and the write half of a tick, too --
    the read succeeds (stale-but-fine state) but the command that follows
    isn't acknowledged. Same fault, different half of the round trip."""
    cfg = _cfg()
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=10.0)
    cabinet = FakeCabinet()
    cabinet.command("NS")

    class DropsCommandsOnly(FakeCabinet):
        """Reads succeed normally; only the write half of the round trip
        drops, simulating comms failing between the read and the command
        that follows it within the same tick."""

        def command(self, phase_id: str) -> bool:
            return False

    flaky = DropsCommandsOnly()
    flaky._reported_phase = "NS"  # noqa: SLF001 -- seed the readback the real command() would have set

    decision = arbiter.tick(cfg, ctx, flaky)

    assert decision.mode == "degraded_comms_lost"
    assert decision.plan is None


def test_C4_power_restart_forces_all_red_then_resumes_cleanly():
    cfg = _cfg()
    cabinet = FakeCabinet()
    cabinet.command("NS")
    cabinet.simulate_power_cycle()

    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=0.0)
    boot_decision = arbiter.tick(cfg, ctx, cabinet)

    assert boot_decision.mode == "failsafe_boot_all_red"
    assert boot_decision.plan is None
    assert cabinet.read_state().phase_id is None
    assert cabinet.read_state().booting is False  # the forced all-red *is* the defined resume step

    # Next tick: a fresh, defined start -- not an assumed resumption of
    # whatever was live before the outage.
    resume_ctx = JunctionContext(
        intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=0.0
    )
    resume_decision = arbiter.tick(cfg, resume_ctx, cabinet)

    assert resume_decision.mode == "fixed_time"
    assert resume_decision.plan is not None


def test_C5_command_readback_divergence_halts_commanding():
    cfg = _cfg()
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=5.0)
    cabinet = FakeCabinet()
    cabinet.command("NS")
    cabinet.force_diverge("EW")  # e.g. a traffic officer forcing the cabinet by hand (E1)

    decision = arbiter.tick(cfg, ctx, cabinet)

    assert decision.mode == "failsafe_divergence"
    assert decision.plan is None
    assert "NS" in decision.events[0]["detail"] and "EW" in decision.events[0]["detail"]


def test_C5_no_false_positive_when_readback_matches():
    cfg = _cfg()
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=5.0)
    cabinet = FakeCabinet()
    cabinet.command("NS")

    decision = arbiter.tick(cfg, ctx, cabinet)

    assert decision.mode != "failsafe_divergence"
