"""`itms_domain.routing` -- EmergencyRoutingConfig + RouteResult value types."""

from __future__ import annotations

import dataclasses
import math

from itms_domain.routing import (
    EmergencyRoutingConfig,
    RouteCostBreakdown,
    RouteResult,
)


def test_default_config_is_valid_and_has_all_severity_keys():
    cfg = EmergencyRoutingConfig()
    assert cfg.validate() == []
    for k in ("low", "medium", "high", "blocked"):
        assert k in cfg.severity_penalty
    assert math.isinf(cfg.severity_penalty["blocked"])


def test_config_weights_are_all_tunable_without_touching_logic():
    cfg = EmergencyRoutingConfig(
        travel_time_weight=2.0,
        congestion_weight=0.0,
        anomaly_weight=5.0,
        signal_delay_weight=0.1,
        disruption_weight=0.0,
        reliability_weight=0.0,
    )
    assert cfg.validate() == []
    d = cfg.as_dict()
    assert d["travel_time_weight"] == 2.0 and d["anomaly_weight"] == 5.0


def test_config_rejects_all_zero_weights():
    cfg = EmergencyRoutingConfig(
        travel_time_weight=0,
        congestion_weight=0,
        anomaly_weight=0,
        signal_delay_weight=0,
        disruption_weight=0,
        reliability_weight=0,
    )
    assert any("non-zero" in p for p in cfg.validate())


def test_config_rejects_a_negative_weight_and_a_missing_severity_key():
    assert any("travel_time_weight" in p for p in
               EmergencyRoutingConfig(travel_time_weight=-1).validate())
    bad = EmergencyRoutingConfig(severity_penalty={"low": 1.2, "medium": 2.0, "high": 4.0})
    assert any("blocked" in p for p in bad.validate())


def test_config_rejects_bad_corridor_and_cooldown():
    assert EmergencyRoutingConfig(corridor_max_simultaneous=0).validate()
    assert EmergencyRoutingConfig(reroute_cooldown_s=-1).validate()


def _route(**over) -> RouteResult:
    cost = RouteCostBreakdown(
        travel_time_s=250.0, congestion_cost=1.4, anomaly_cost=0.0,
        signal_delay_s=44.0, disruption_cost=0.6, reliability_cost=0.2,
        total_score=28.7,
    )
    kw = dict(
        edges=("E1", "E2", "E3", "E4"),
        total_distance_m=3800.0,
        total_travel_time_s=250.0,
        eta_s=272.0,
        n_intersections=6,
        signalised_intersections=("J1", "J2", "J3", "J4"),
        congested_segments=("E2",),
        anomalous_segments_avoided=("E9",),
        cost=cost,
        reliable=True,
        weights_used={"anomaly_weight": 1.0},
        rank=0,
    )
    kw.update(over)
    return RouteResult(**kw)


def test_route_result_score_is_the_total_and_summary_is_complete():
    r = _route()
    assert r.score == 28.7
    s = r.summary()
    assert s["eta_s"] == 272.0
    assert s["signalised_intersections"] == ["J1", "J2", "J3", "J4"]
    assert s["anomalous_segments_avoided"] == ["E9"]
    assert s["cost"]["total_score"] == 28.7
    assert s["weights_used"] == {"anomaly_weight": 1.0}
    assert s["rank"] == 0


def test_route_results_are_comparable_by_score_for_ranking():
    a = _route(cost=dataclasses.replace(_route().cost, total_score=28.7))
    b = _route(cost=dataclasses.replace(_route().cost, total_score=32.4), rank=1)
    best = min([a, b], key=lambda r: r.score)
    assert best is a


def test_route_result_is_frozen():
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        _route().edges = ("X",)  # type: ignore[misc]
