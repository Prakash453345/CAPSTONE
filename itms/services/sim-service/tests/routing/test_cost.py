"""`RouteCostModel.edge_cost` -- the ITMS dynamic edge cost."""

from __future__ import annotations

import math

import pytest
from itms_domain import EmergencyRoutingConfig
from sim_service.routing.cost import EdgeConditions, RouteCostModel
from sim_service.routing.graph import EdgeInfo

_EDGE = EdgeInfo(
    edge_id="E1",
    length_m=200.0,
    num_lanes=2,
    speed_limit_mps=10.0,  # -> 20 s free-flow
    from_junction="J0",
    to_junction="J1",
    start_xy=(0.0, 0.0),
    end_xy=(200.0, 0.0),
)


def _model(**cfg) -> RouteCostModel:
    return RouteCostModel(EmergencyRoutingConfig(**cfg))


def test_free_flow_edge_costs_only_travel_time_and_disruption():
    parts = _model().edge_cost(_EDGE, EdgeConditions())
    assert parts.travel_time_s == pytest.approx(20.0)
    assert parts.congestion_cost == 0.0
    assert parts.anomaly_cost == 0.0
    assert parts.signal_delay_s == 0.0
    assert parts.disruption_cost > 0.0  # length term always applies
    assert parts.weighted_total > 0.0


def test_congestion_raises_travel_time_and_adds_a_congestion_term():
    free = _model().edge_cost(_EDGE, EdgeConditions())
    jam = _model().edge_cost(_EDGE, EdgeConditions(congestion=0.9))
    assert jam.travel_time_s > free.travel_time_s
    assert jam.congestion_cost > 0.0
    assert jam.weighted_total > free.weighted_total


def test_blocked_severity_is_infinite():
    parts = _model().edge_cost(_EDGE, EdgeConditions(anomaly_severity="blocked"))
    assert math.isinf(parts.weighted_total)


def test_partial_anomaly_penalty_is_ordered_by_severity():
    m = _model()
    lo = m.edge_cost(_EDGE, EdgeConditions(anomaly_severity="low", anomaly_impact=0.2))
    md = m.edge_cost(_EDGE, EdgeConditions(anomaly_severity="medium", anomaly_impact=0.5))
    hi = m.edge_cost(_EDGE, EdgeConditions(anomaly_severity="high", anomaly_impact=0.8))
    assert 0 < lo.anomaly_cost < md.anomaly_cost < hi.anomaly_cost
    assert lo.weighted_total < md.weighted_total < hi.weighted_total


def test_signal_delay_depends_on_phase_and_only_applies_when_signalised():
    m = _model()
    none = m.edge_cost(_EDGE, EdgeConditions(entry_is_signalised=False, entry_signal_phase="red"))
    grn = m.edge_cost(_EDGE, EdgeConditions(entry_is_signalised=True, entry_signal_phase="green"))
    red = m.edge_cost(_EDGE, EdgeConditions(entry_is_signalised=True, entry_signal_phase="red"))
    unk = m.edge_cost(_EDGE, EdgeConditions(entry_is_signalised=True, entry_signal_phase=None))
    assert none.signal_delay_s == 0.0
    assert 0 < grn.signal_delay_s < unk.signal_delay_s < red.signal_delay_s


def test_reliability_rises_with_variance_and_with_an_active_anomaly():
    m = _model()
    calm = m.edge_cost(_EDGE, EdgeConditions(congestion_variance=0.0))
    noisy = m.edge_cost(_EDGE, EdgeConditions(congestion_variance=0.2))
    anom = m.edge_cost(_EDGE, EdgeConditions(anomaly_severity="medium", anomaly_impact=0.3))
    assert noisy.reliability_cost > calm.reliability_cost
    assert anom.reliability_cost > calm.reliability_cost


def test_weights_are_configurable_zeroing_one_drops_its_term():
    on = _model(anomaly_weight=1.0)
    off = _model(anomaly_weight=0.0)
    ec = EdgeConditions(anomaly_severity="high", anomaly_impact=0.8)
    assert on.edge_cost(_EDGE, ec).weighted_total > off.edge_cost(_EDGE, ec).weighted_total
    assert off.edge_cost(_EDGE, ec).anomaly_cost == 0.0


def test_scaling_a_weight_up_scales_only_that_component():
    base = _model(congestion_weight=0.5)
    heavy = _model(congestion_weight=2.0)
    ec = EdgeConditions(congestion=0.8)
    assert heavy.edge_cost(_EDGE, ec).congestion_cost == pytest.approx(
        4.0 * base.edge_cost(_EDGE, ec).congestion_cost
    )
