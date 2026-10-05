"""The normalised anomaly model [project direction: "normalize these into the
same incident/anomaly domain model"].

`itms_domain.incident.Incident` is the M6 *detection* lifecycle -- a candidate
that an operator confirms or rejects, carrying conformal scores and a hash
chain. `Anomaly` here is the flatter, source-agnostic record of "there is a
disruption on this road segment right now" that the emergency router and the
anomaly-impact model consume. Every producer normalises to it:

    OPERATOR       -> created directly from the Create Anomaly panel
    SUMO_INJECTOR  -> the automated M6 injector's stall / lane-block
    GRAPH_MODEL    -> an M6 Incident, once an operator confirms it
    VISION         -> M8, later

Pure value object: no I/O, no clock reads (times are passed in), like the rest
of `itms_domain`. The numeric `estimated_impact` is supplied by the caller
(computed from a config), never hard-coded here -- the domain type stays dumb
about the weights.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum


class AnomalySource(StrEnum):
    OPERATOR = "operator"
    SUMO_INJECTOR = "sumo_injector"
    GRAPH_MODEL = "graph_model"
    VISION = "vision"


class AnomalyType(StrEnum):
    ACCIDENT = "accident"
    VEHICLE_BREAKDOWN = "vehicle_breakdown"
    LANE_BLOCKAGE = "lane_blockage"
    ROAD_OBSTRUCTION = "road_obstruction"
    HEAVY_CONGESTION = "heavy_congestion"
    STALLED_VEHICLE = "stalled_vehicle"  # the M6 injector's stall
    FIRE = "fire"  # M8 fire/smoke candidate (operator confirms, ADR-006)
    UNKNOWN = "unknown"


class AnomalySeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"  # the edge is fully unavailable -> edgeCost = INF


class AnomalyStatus(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


TERMINAL_ANOMALY_STATES: frozenset[AnomalyStatus] = frozenset(
    {AnomalyStatus.RESOLVED, AnomalyStatus.CANCELLED}
)


@dataclass(frozen=True)
class Anomaly:
    """One disruption on one SUMO edge. Immutable -- lifecycle changes return a
    new value (`resolved()`, `cancelled()`), matching the rest of the domain
    layer.

    `estimated_impact` is a 0..1 fraction: the share of the edge's normal
    capacity/speed lost to this anomaly. 1.0 is equivalent to BLOCKED. The
    router turns it into an edge-cost penalty via its config; the sim turns it
    into a `traci.lane.setMaxSpeed` fraction. `BLOCKED` always means fully
    unavailable regardless of the number.
    """

    anomaly_id: str
    source: AnomalySource
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    edge_id: str
    status: AnomalyStatus
    created_at_ms: int
    start_time_ms: int
    estimated_impact: float
    lane_id: str | None = None
    duration_s: float | None = None  # None = until explicitly resolved
    position_m: float | None = None  # metres along the edge, optional
    detail: str = ""
    operator: str = ""  # who created / owns it, when source == OPERATOR
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.estimated_impact <= 1.0:
            raise ValueError(
                f"estimated_impact must be in [0, 1], got {self.estimated_impact}"
            )
        if self.duration_s is not None and self.duration_s <= 0:
            raise ValueError(f"duration_s must be > 0 or None, got {self.duration_s}")

    # ---- derived -----------------------------------------------------

    @property
    def is_blocking(self) -> bool:
        return self.severity is AnomalySeverity.BLOCKED

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ANOMALY_STATES

    def expires_at_ms(self) -> int | None:
        if self.duration_s is None:
            return None
        return self.start_time_ms + int(self.duration_s * 1000)

    def is_active_at(self, now_ms: int) -> bool:
        """ACTIVE and not past its duration. A time-boxed anomaly that has run
        out is treated as no longer affecting the network even before something
        explicitly resolves it."""
        if self.status is not AnomalyStatus.ACTIVE:
            return False
        expiry = self.expires_at_ms()
        return expiry is None or now_ms < expiry

    # ---- transitions -----------------------------------------------

    def resolved(self, *, at_ms: int, reason: str = "") -> Anomaly:
        """Mark cleared -- the disruption is over and the road is normal again."""
        if self.is_terminal:
            return self
        meta = dict(self.metadata)
        if reason:
            meta["resolved_reason"] = reason
        meta["resolved_at_ms"] = str(at_ms)
        return replace(self, status=AnomalyStatus.RESOLVED, metadata=meta)

    def cancelled(self, *, at_ms: int, reason: str = "") -> Anomaly:
        """Operator withdrew it (created by mistake, wrong location, ...).
        Distinct from RESOLVED: nothing about the road actually changed."""
        if self.is_terminal:
            return self
        meta = dict(self.metadata)
        if reason:
            meta["cancelled_reason"] = reason
        meta["cancelled_at_ms"] = str(at_ms)
        return replace(self, status=AnomalyStatus.CANCELLED, metadata=meta)

    # ---- factory --------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        anomaly_id: str,
        source: AnomalySource,
        anomaly_type: AnomalyType,
        severity: AnomalySeverity,
        edge_id: str,
        at_ms: int,
        estimated_impact: float,
        lane_id: str | None = None,
        duration_s: float | None = None,
        position_m: float | None = None,
        start_time_ms: int | None = None,
        detail: str = "",
        operator: str = "",
        metadata: Mapping[str, str] | None = None,
    ) -> Anomaly:
        """A fresh ACTIVE anomaly. `start_time_ms` defaults to `at_ms` (it
        starts now); pass it explicitly to schedule one."""
        return cls(
            anomaly_id=anomaly_id,
            source=source,
            anomaly_type=anomaly_type,
            severity=severity,
            edge_id=edge_id,
            status=AnomalyStatus.ACTIVE,
            created_at_ms=at_ms,
            start_time_ms=at_ms if start_time_ms is None else start_time_ms,
            estimated_impact=estimated_impact,
            lane_id=lane_id,
            duration_s=duration_s,
            position_m=position_m,
            detail=detail,
            operator=operator,
            metadata=dict(metadata or {}),
        )
