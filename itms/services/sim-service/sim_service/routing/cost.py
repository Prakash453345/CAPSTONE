"""`RouteCostModel` -- the ITMS-specific dynamic edge cost.

    weighted_total =  w_tt   * (effective_travel_time / travel_time_ref)
                    + w_cong * congestion
                    + w_anom * anomaly_norm
                    + w_sig  * (signal_delay / travel_time_ref)
                    + w_disr * (length / disruption_ref)
                    + w_rel  * reliability_norm

Every weight and reference is an `itms_domain.EmergencyRoutingConfig` field --
nothing here is a magic number. Each term is normalised to roughly 0..1 before
the weight applies, so a large raw scale (metres, seconds) cannot dominate a
bounded one (a 0..1 congestion index). BLOCKED-severity edges are removed from
the graph before search; if one is costed anyway this returns +inf.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from itms_domain import EmergencyRoutingConfig

from sim_service.routing.graph import EdgeInfo

# clamp for the congestion-derived speed factor: even a jammed edge is treated
# as crawling, not stopped, unless it is an outright BLOCKED anomaly
_MIN_SPEED_FRAC = 0.12


@dataclass(frozen=True)
class EdgeConditions:
    """Live state for one edge at planning time. All optional -- an edge with
    no data is treated as free-flowing and unsignalised."""

    congestion: float = 0.0           # 0..1 occupancy / congestion index
    # live mean speed / speed limit; derived from `congestion` when None
    mean_speed_frac: float | None = None
    congestion_variance: float = 0.0  # recent variance of `congestion`, 0..~0.25
    anomaly_severity: str | None = None   # None | "low" | "medium" | "high" | "blocked"
    anomaly_impact: float = 0.0       # 0..1 estimated_impact of the active anomaly
    entry_is_signalised: bool = False
    entry_signal_phase: str | None = None  # "green" | "yellow" | "red" | None (unknown)

    @property
    def has_active_anomaly(self) -> bool:
        return self.anomaly_severity is not None

    @property
    def is_blocked(self) -> bool:
        return self.anomaly_severity == "blocked"


@dataclass(frozen=True)
class EdgeCostParts:
    """The per-edge cost broken out. `weighted_total` is what the search
    minimises; the raw `travel_time_s` / `signal_delay_s` are summed
    separately for the route's ETA and its explanation panel."""

    travel_time_s: float
    congestion_cost: float
    anomaly_cost: float
    signal_delay_s: float
    disruption_cost: float
    reliability_cost: float
    weighted_total: float


class RouteCostModel:
    def __init__(self, config: EmergencyRoutingConfig | None = None):
        self.config = config or EmergencyRoutingConfig()

    def edge_cost(self, edge: EdgeInfo, cond: EdgeConditions | None) -> EdgeCostParts:
        c = self.config
        cond = cond or EdgeConditions()

        if cond.is_blocked:
            return EdgeCostParts(
                travel_time_s=math.inf,
                congestion_cost=math.inf,
                anomaly_cost=math.inf,
                signal_delay_s=0.0,
                disruption_cost=0.0,
                reliability_cost=0.0,
                weighted_total=math.inf,
            )

        # --- travel time (congestion slows you down) ---
        speed_frac = (
            cond.mean_speed_frac
            if cond.mean_speed_frac is not None
            else 1.0 - 0.7 * _clamp01(cond.congestion)
        )
        speed_frac = max(_MIN_SPEED_FRAC, min(1.0, speed_frac))
        travel_time_s = edge.free_flow_time_s / speed_frac
        tt_norm = travel_time_s / max(1e-6, c.travel_time_ref_s)

        # --- congestion ---
        congestion_norm = _clamp01(cond.congestion)

        # --- anomaly (partial; BLOCKED handled above) ---
        anomaly_norm = 0.0
        if cond.has_active_anomaly:
            penalty = c.severity_penalty.get(cond.anomaly_severity or "", 1.0)
            if not math.isfinite(penalty):
                anomaly_norm = 10.0  # defensive: BLOCKED slipped through
            else:
                anomaly_norm = (penalty - 1.0) + c.impact_penalty_scale * _clamp01(
                    cond.anomaly_impact
                )

        # --- signal delay (seconds, at the junction entering this edge) ---
        signal_delay_s = 0.0
        if cond.entry_is_signalised:
            phase = cond.entry_signal_phase or "unknown"
            fallback = c.signal_delay_s.get("unknown", 0.0)
            signal_delay_s = float(c.signal_delay_s.get(phase, fallback))
        sig_norm = signal_delay_s / max(1e-6, c.travel_time_ref_s)

        # --- disruption (longer exposed segment = worse for an emergency) ---
        disruption_norm = edge.length_m / max(1e-6, c.disruption_ref_m)

        # --- reliability (unstable / anomalous edge is less desirable) ---
        reliability_norm = c.reliability_variance_weight * min(0.5, cond.congestion_variance)
        if cond.has_active_anomaly:
            reliability_norm += 0.3

        weighted_total = (
            c.travel_time_weight * tt_norm
            + c.congestion_weight * congestion_norm
            + c.anomaly_weight * anomaly_norm
            + c.signal_delay_weight * sig_norm
            + c.disruption_weight * disruption_norm
            + c.reliability_weight * reliability_norm
        )

        return EdgeCostParts(
            travel_time_s=travel_time_s,
            congestion_cost=c.congestion_weight * congestion_norm,
            anomaly_cost=c.anomaly_weight * anomaly_norm,
            signal_delay_s=signal_delay_s,
            disruption_cost=c.disruption_weight * disruption_norm,
            reliability_cost=c.reliability_weight * reliability_norm,
            weighted_total=weighted_total,
        )


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x
