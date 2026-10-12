"""Emergency-routing value types and the one centralised config.

[project direction]: the path search is a standard graph search; the
*contribution* is the dynamic cost/decision framework -- and its weights must
not be scattered as magic numbers. `EmergencyRoutingConfig` is that single
object. `RouteResult` / `RouteCostBreakdown` are what the planner returns so
the UI can answer "why this route".

Pure data. The planner (`sim-service`) owns the graph search and the live
metric reads; these types just carry the inputs' shapes and the outputs'.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

_DEFAULT_SEVERITY_PENALTY: dict[str, float] = {
    # multiplicative factor on an edge's base cost while an anomaly of this
    # severity is active on it. BLOCKED is infinite = the edge drops out.
    "low": 1.25,
    "medium": 2.0,
    "high": 4.0,
    "blocked": math.inf,
}

_DEFAULT_SIGNAL_DELAY_S: dict[str, float] = {
    # expected extra seconds crossing a signalised junction, by the phase the
    # approach currently shows. "unknown" = no live phase data for it.
    "green": 2.0,
    "yellow": 6.0,
    "red": 22.0,
    "unknown": 12.0,
}


@dataclass(frozen=True)
class EmergencyRoutingConfig:
    """Every weight and threshold the emergency router uses, in one place.
    Change these without touching the search or the cost model.

        edgeCost = travel_time_weight   * travel_time_norm
                 + congestion_weight    * congestion_norm
                 + anomaly_weight       * anomaly_norm
                 + signal_delay_weight  * signal_delay_norm
                 + disruption_weight    * disruption_norm
                 + reliability_weight   * reliability_norm

    Each component is normalised (roughly 0..1 over a segment) before the
    weights apply, so a big raw scale can't dominate. BLOCKED edges are removed
    from the graph before search rather than carried as an infinite cost.
    """

    # --- component weights (alpha .. zeta) ---
    travel_time_weight: float = 1.0
    congestion_weight: float = 0.6
    anomaly_weight: float = 1.0
    signal_delay_weight: float = 0.4
    disruption_weight: float = 0.5
    reliability_weight: float = 0.3

    # --- anomaly impact ---
    severity_penalty: Mapping[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_SEVERITY_PENALTY)
    )
    # additional linear penalty scaled by an anomaly's estimated_impact (0..1)
    impact_penalty_scale: float = 3.0

    # --- signal delay ---
    signal_delay_s: Mapping[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_SIGNAL_DELAY_S)
    )

    # --- reliability ---
    # weight on recent congestion variance on the edge (unstable = less desirable)
    reliability_variance_weight: float = 1.5
    # a route whose reliability_cost exceeds this is flagged unreliable
    reliability_reject_threshold: float = 0.85

    # --- normalisation references ---
    # a segment taking this many seconds of free-flow travel maps to ~1.0
    travel_time_ref_s: float = 60.0
    # a segment this many metres long maps to ~1.0 for the disruption term
    disruption_ref_m: float = 400.0

    # --- multi-route ---
    max_alternatives: int = 2
    # An alternative is offered only if it is a genuinely different way to get
    # there: its weighted cost is at most `alternative_max_stretch` x the best
    # route's, and at most `alternative_max_overlap` of its length (source and
    # destination roads excluded) runs along any route already offered. On a
    # grid this stops "the same route with one block's detour" being shown as
    # an alternative, and stops wildly longer routes padding the list.
    alternative_max_stretch: float = 1.6
    alternative_max_overlap: float = 0.7

    # --- last-resort routing ---
    # `RoutePlanner.plan`'s primary pass always excludes BLOCKED edges. If that
    # leaves no path at all -- the blockage sits on the only way through --
    # it retries once allowing them, so a real dispatch never dead-ends over
    # one bad segment. This is the finite anomaly-cost stand-in a BLOCKED edge
    # gets in that fallback pass: large enough that any real alternative always
    # scores lower (so the primary pass still wins whenever one exists), but
    # finite so the resulting route has a displayable ETA/score instead of
    # infinity. The route is always marked `reliable=False` and its
    # `forced_through` edges are reported so the UI can warn explicitly.
    blocked_fallback_anomaly_norm: float = 10.0

    # --- continuous re-routing ---
    reroute_cost_increase_frac: float = 0.35  # recompute if remaining cost jumps this much
    reroute_cooldown_s: float = 30.0          # never recompute more often than this
    reroute_min_progress_frac: float = 0.03   # ignore triggers in the first 3% of the route
    reroute_on_blocked_edge: bool = True
    reroute_on_new_severe_anomaly: bool = True

    # --- green corridor ---
    corridor_prepare_lead_s: float = 15.0     # open a junction this long before predicted arrival
    corridor_release_lag_s: float = 4.0       # keep it held this long after predicted pass
    corridor_min_gap_s: float = 5.0           # min spacing between two junctions' windows
    corridor_max_simultaneous: int = 3        # hard cap on concurrent preemptions per corridor

    def validate(self) -> list[str]:
        problems: list[str] = []
        weights = {
            "travel_time_weight": self.travel_time_weight,
            "congestion_weight": self.congestion_weight,
            "anomaly_weight": self.anomaly_weight,
            "signal_delay_weight": self.signal_delay_weight,
            "disruption_weight": self.disruption_weight,
            "reliability_weight": self.reliability_weight,
        }
        for name, value in weights.items():
            if value < 0 or not math.isfinite(value):
                problems.append(f"{name} must be finite and >= 0, got {value}")
        if all(v == 0 for v in weights.values()):
            problems.append("at least one cost weight must be non-zero")
        for key in ("low", "medium", "high", "blocked"):
            if key not in self.severity_penalty:
                problems.append(f"severity_penalty missing key {key!r}")
        if self.reroute_cooldown_s < 0:
            problems.append("reroute_cooldown_s must be >= 0")
        if self.blocked_fallback_anomaly_norm <= 0 or not math.isfinite(
            self.blocked_fallback_anomaly_norm
        ):
            problems.append("blocked_fallback_anomaly_norm must be finite and > 0")
        if self.max_alternatives < 0:
            problems.append("max_alternatives must be >= 0")
        if not (self.alternative_max_stretch >= 1.0):
            problems.append("alternative_max_stretch must be >= 1 (the best route has stretch 1)")
        if not (0.0 <= self.alternative_max_overlap <= 1.0):
            problems.append("alternative_max_overlap must be between 0 and 1")
        if self.corridor_max_simultaneous < 1:
            problems.append("corridor_max_simultaneous must be >= 1")
        if not 0.0 < self.reliability_reject_threshold:
            problems.append("reliability_reject_threshold must be > 0")
        return problems

    def as_dict(self) -> dict[str, float]:
        """Flat float view of the scalar knobs -- goes into `RouteResult` for
        the "why this route" panel and the audit log."""
        return {
            "travel_time_weight": self.travel_time_weight,
            "congestion_weight": self.congestion_weight,
            "anomaly_weight": self.anomaly_weight,
            "signal_delay_weight": self.signal_delay_weight,
            "disruption_weight": self.disruption_weight,
            "reliability_weight": self.reliability_weight,
            "impact_penalty_scale": self.impact_penalty_scale,
            "reliability_variance_weight": self.reliability_variance_weight,
            "alternative_max_stretch": self.alternative_max_stretch,
            "alternative_max_overlap": self.alternative_max_overlap,
        }


@dataclass(frozen=True)
class RouteCostBreakdown:
    """The per-component cost of a whole route -- summed over its edges, in the
    same units the config's weights produced. `total_score` is the number the
    planner minimises; lower is better."""

    travel_time_s: float
    congestion_cost: float
    anomaly_cost: float
    signal_delay_s: float
    disruption_cost: float
    reliability_cost: float
    total_score: float

    def as_dict(self) -> dict[str, float]:
        return {
            "travel_time_s": self.travel_time_s,
            "congestion_cost": self.congestion_cost,
            "anomaly_cost": self.anomaly_cost,
            "signal_delay_s": self.signal_delay_s,
            "disruption_cost": self.disruption_cost,
            "reliability_cost": self.reliability_cost,
            "total_score": self.total_score,
        }


@dataclass(frozen=True)
class RouteResult:
    """One candidate route with everything the UI needs to explain the choice.
    `edges` is the ordered SUMO edge sequence from source to destination."""

    edges: tuple[str, ...]
    total_distance_m: float
    total_travel_time_s: float
    eta_s: float
    n_intersections: int
    signalised_intersections: tuple[str, ...]
    congested_segments: tuple[str, ...]
    anomalous_segments_avoided: tuple[str, ...]
    cost: RouteCostBreakdown
    reliable: bool
    weights_used: Mapping[str, float] = field(default_factory=dict)
    rank: int = 0  # 0 = recommended, 1.. = alternatives
    # Edges this route had to cross despite being flagged BLOCKED, because no
    # alternative existed at all -- `RoutePlanner.plan`'s last-resort fallback.
    # Empty on every ordinary route. Non-empty implies `reliable is False`.
    forced_through: tuple[str, ...] = ()

    @property
    def score(self) -> float:
        return self.cost.total_score

    def summary(self) -> dict:
        """The route-preview payload (matches the UI's Route Preview panel)."""
        return {
            "edges": list(self.edges),
            "eta_s": self.eta_s,
            "total_distance_m": self.total_distance_m,
            "n_intersections": self.n_intersections,
            "signalised_intersections": list(self.signalised_intersections),
            "congested_segments": list(self.congested_segments),
            "anomalous_segments_avoided": list(self.anomalous_segments_avoided),
            "forced_through": list(self.forced_through),
            "reliable": self.reliable,
            "rank": self.rank,
            "cost": self.cost.as_dict(),
            "weights_used": dict(self.weights_used),
        }
