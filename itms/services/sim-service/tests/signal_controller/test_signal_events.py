"""Round-trip proof that `arbiter.tick()`'s `Decision.events` payloads
actually match `contracts/events/signal_changed.avsc` /
`signal_faulted.avsc` -- PROGRESS.md's M2 section claimed this was
"verified to round-trip through itms_common.encode_envelope/decode_envelope"
but no test ever checked it in; this closes that gap for real, using the
same `_cfg()`/`FakeCabinet` fixtures `test_fault_injection.py` already
established for exercising both a healthy tick and a faulted one."""

from __future__ import annotations

from itms_common.events import decode_envelope, encode_envelope
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


def test_signal_changed_event_round_trips_through_the_real_schema():
    cfg = _cfg()
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=0.0)
    decision = arbiter.tick(cfg, ctx, FakeCabinet())
    assert decision.mode == "fixed_time"
    [payload] = decision.events

    raw = encode_envelope(
        event_type="SignalChanged",
        source="sim-service",
        payload=payload,
        partition_key=payload["intersection_id"],
    )
    envelope = decode_envelope(raw)

    assert envelope["event_type"] == "SignalChanged"
    assert envelope["partition_key"] == "J"
    assert envelope["payload"] == payload
    assert envelope["payload"]["phase_id"] == "NS"
    assert envelope["payload"]["source"] == "fixed_time"


def test_signal_faulted_event_round_trips_through_the_real_schema():
    cfg = _cfg()
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=0.0)
    cabinet = FakeCabinet()
    cabinet.trip_conflict_monitor()  # C2

    decision = arbiter.tick(cfg, ctx, cabinet)
    assert decision.mode == "failsafe_hardware_override"
    [payload] = decision.events

    raw = encode_envelope(
        event_type="SignalFaulted",
        source="sim-service",
        payload=payload,
        partition_key=payload["intersection_id"],
    )
    envelope = decode_envelope(raw)

    assert envelope["event_type"] == "SignalFaulted"
    assert envelope["partition_key"] == "J"
    assert envelope["payload"] == payload
    assert envelope["payload"]["fault_type"] == "conflict_monitor_trip"
