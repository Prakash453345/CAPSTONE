"""The incident state machine and its tamper-evident audit chain. Pure --
no bus, no clock, no SUMO; every timestamp is passed in."""

from __future__ import annotations

import dataclasses
from itertools import pairwise

import pytest
from itms_domain.incident import (
    GENESIS_HASH,
    IllegalTransition,
    Incident,
    IncidentAction,
    IncidentClass,
    IncidentState,
)


def _candidate(**overrides) -> Incident:
    kwargs = dict(
        incident_id="inc-1",
        link_id="L3",
        intersection_id="J2",
        at_ms=1_000,
        graph_score=4.2,
        fused_probability=0.91,
        threshold_tau=0.80,
        detector_version="graph-ae@abc/conformal@def",
    )
    kwargs.update(overrides)
    return Incident.raise_candidate(**kwargs)


# ---- transitions ----------------------------------------------------------


def test_raise_produces_a_candidate_with_a_genesis_entry():
    inc = _candidate()
    assert inc.state is IncidentState.CANDIDATE
    assert inc.classification is IncidentClass.UNKNOWN
    assert len(inc.history) == 1
    genesis = inc.history[0]
    assert genesis.action is IncidentAction.RAISE
    assert genesis.from_state is None
    assert genesis.prev_hash == GENESIS_HASH
    assert inc.chain_head == genesis.entry_hash


def test_candidate_confirms_to_detected_and_records_operator_and_class():
    inc = _candidate().apply(
        IncidentAction.CONFIRM,
        at_ms=9_000,
        actor="operator:alice",
        classification=IncidentClass.STALL,
    )
    assert inc.state is IncidentState.CONFIRMED
    assert inc.classification is IncidentClass.STALL
    assert inc.history[-1].actor == "operator:alice"
    assert inc.history[-1].classification is IncidentClass.STALL
    assert inc.confirmation_latency_ms() == 8_000


def test_candidate_rejects_to_terminal():
    inc = _candidate().apply(
        IncidentAction.REJECT, at_ms=5_000, actor="operator:bob", detail="shift change queue"
    )
    assert inc.state is IncidentState.REJECTED
    assert inc.is_terminal


def test_candidate_expires_to_terminal():
    inc = _candidate().apply(IncidentAction.EXPIRE, at_ms=200_000, actor="system:timeout")
    assert inc.state is IncidentState.EXPIRED
    assert inc.is_terminal


def test_confirmed_refreshes_in_place_then_clears():
    inc = _candidate().apply(IncidentAction.CONFIRM, at_ms=9_000, actor="operator:alice")
    inc = inc.apply(
        IncidentAction.REFRESH, at_ms=12_000, actor="detector", fused_probability=0.97
    )
    assert inc.state is IncidentState.CONFIRMED
    assert inc.fused_probability == 0.97
    inc = inc.apply(
        IncidentAction.CLEAR, at_ms=60_000, actor="operator:alice", detail="link speed recovered"
    )
    assert inc.state is IncidentState.CLEARED
    assert inc.is_terminal
    assert [t.action for t in inc.history] == [
        IncidentAction.RAISE,
        IncidentAction.CONFIRM,
        IncidentAction.REFRESH,
        IncidentAction.CLEAR,
    ]


@pytest.mark.parametrize(
    "action",
    [IncidentAction.CONFIRM, IncidentAction.REJECT, IncidentAction.REFRESH, IncidentAction.CLEAR],
)
def test_no_action_is_legal_on_a_terminal_incident(action):
    inc = _candidate().apply(IncidentAction.REJECT, at_ms=5_000, actor="operator:bob")
    with pytest.raises(IllegalTransition):
        inc.apply(action, at_ms=6_000, actor="operator:bob")


def test_cannot_clear_or_refresh_a_bare_candidate():
    inc = _candidate()
    with pytest.raises(IllegalTransition):
        inc.apply(IncidentAction.CLEAR, at_ms=2_000, actor="operator:alice")
    with pytest.raises(IllegalTransition):
        inc.apply(IncidentAction.REFRESH, at_ms=2_000, actor="detector")


def test_confirm_is_rejected_a_second_time():
    inc = _candidate().apply(IncidentAction.CONFIRM, at_ms=9_000, actor="operator:alice")
    with pytest.raises(IllegalTransition):
        inc.apply(IncidentAction.CONFIRM, at_ms=10_000, actor="operator:alice")


def test_apply_returns_a_new_value_and_leaves_the_original_untouched():
    original = _candidate()
    confirmed = original.apply(IncidentAction.CONFIRM, at_ms=9_000, actor="operator:alice")
    assert original.state is IncidentState.CANDIDATE
    assert len(original.history) == 1
    assert confirmed is not original


# ---- audit chain --------------------------------------------------------


def test_a_clean_lifecycle_verifies():
    inc = (
        _candidate()
        .apply(IncidentAction.CONFIRM, at_ms=9_000, actor="operator:alice",
               classification=IncidentClass.LANE_BLOCK)
        .apply(IncidentAction.REFRESH, at_ms=12_000, actor="detector", fused_probability=0.95)
        .apply(IncidentAction.CLEAR, at_ms=60_000, actor="operator:alice")
    )
    assert inc.verify_chain()
    # every link points at its predecessor's hash
    for prev, nxt in pairwise(inc.history):
        assert nxt.prev_hash == prev.entry_hash


def test_editing_a_recorded_field_breaks_verification():
    inc = _candidate().apply(
        IncidentAction.REJECT, at_ms=5_000, actor="operator:bob", detail="not an incident"
    )
    tampered_history = list(inc.history)
    tampered_history[-1] = dataclasses.replace(tampered_history[-1], detail="actually an incident")
    tampered = dataclasses.replace(inc, history=tuple(tampered_history))
    assert not tampered.verify_chain()


def test_reordering_entries_breaks_verification():
    inc = (
        _candidate()
        .apply(IncidentAction.CONFIRM, at_ms=9_000, actor="operator:alice")
        .apply(IncidentAction.REFRESH, at_ms=12_000, actor="detector", fused_probability=0.95)
    )
    swapped = dataclasses.replace(inc, history=(inc.history[0], inc.history[2], inc.history[1]))
    assert not swapped.verify_chain()


def test_dropping_an_entry_breaks_verification():
    inc = (
        _candidate()
        .apply(IncidentAction.CONFIRM, at_ms=9_000, actor="operator:alice")
        .apply(IncidentAction.REFRESH, at_ms=12_000, actor="detector", fused_probability=0.95)
    )
    without_confirm = dataclasses.replace(inc, history=(inc.history[0], inc.history[2]))
    assert not without_confirm.verify_chain()


def test_two_identical_lifecycles_hash_identically():
    a = _candidate().apply(IncidentAction.CONFIRM, at_ms=9_000, actor="operator:alice")
    b = _candidate().apply(IncidentAction.CONFIRM, at_ms=9_000, actor="operator:alice")
    assert a.chain_head == b.chain_head


def test_a_different_timestamp_changes_the_chain_head():
    a = _candidate().apply(IncidentAction.CONFIRM, at_ms=9_000, actor="operator:alice")
    b = _candidate().apply(IncidentAction.CONFIRM, at_ms=9_001, actor="operator:alice")
    assert a.chain_head != b.chain_head
