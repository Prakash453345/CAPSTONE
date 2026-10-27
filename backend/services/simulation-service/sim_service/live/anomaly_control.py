"""Operator-created anomalies applied to the live SUMO simulation.

The human-controlled counterpart to the automated M6 `IncidentInjector`
(`control/anomaly/injector.py`), kept as a SEPARATE code path per the project
direction: the injector is the reproducible evaluation harness; this is
free-form scenario creation. Both ultimately do the same minimal, reversible
TraCI mutation -- reduce a lane's max speed and restore it -- so the overlap
is two `traci` calls, not shared behaviour worth abstracting.

Flow: `run_live`'s command handler calls `handle_create` / `handle_clear`;
`tick` auto-expires time-boxed anomalies and periodically re-publishes active
ones so a late-connecting client catches up. Every state change is queued as
an `AnomalyUpdated` payload for `run_live` to publish on `anomaly.updated`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

import traci
from itms_domain import Anomaly, AnomalySeverity, AnomalySource, AnomalyType

from sim_service.live.timeparse import epoch_ms

log = logging.getLogger("sim-service.live.anomaly")

# Near-zero crawl for a BLOCKED edge -- matches injector._BLOCK_SPEED_MPS.
_BLOCK_SPEED_MPS = 0.1


@dataclass(frozen=True)
class AnomalyImpactConfig:
    """Severity -> effect. `speed_keep_frac` is the fraction of a lane's
    original max speed left in place while the anomaly is active (BLOCKED is
    handled as a near-zero absolute instead). `estimated_impact` is the 0..1
    value handed to the routing cost model. Configurable, in one place --
    never a magic number in the mutation code."""

    speed_keep_frac: Mapping[str, float] = field(
        default_factory=lambda: {"low": 0.70, "medium": 0.45, "high": 0.20, "blocked": 0.0}
    )
    estimated_impact: Mapping[str, float] = field(
        default_factory=lambda: {"low": 0.25, "medium": 0.50, "high": 0.80, "blocked": 1.0}
    )
    republish_interval_s: float = 10.0


_TYPE_MAP = {
    "ACCIDENT": AnomalyType.ACCIDENT,
    "VEHICLE_BREAKDOWN": AnomalyType.VEHICLE_BREAKDOWN,
    "LANE_BLOCKAGE": AnomalyType.LANE_BLOCKAGE,
    "ROAD_OBSTRUCTION": AnomalyType.ROAD_OBSTRUCTION,
    "HEAVY_CONGESTION": AnomalyType.HEAVY_CONGESTION,
    "FIRE": AnomalyType.FIRE,  # a confirmed fire/smoke finding from an uploaded clip
}
_SEV_MAP = {
    "LOW": AnomalySeverity.LOW,
    "MEDIUM": AnomalySeverity.MEDIUM,
    "HIGH": AnomalySeverity.HIGH,
    "BLOCKED": AnomalySeverity.BLOCKED,
}


@dataclass
class _Active:
    anomaly: Anomaly
    lane_originals: dict[str, float]  # lane_id -> pre-anomaly max speed (m/s)
    expire_at_sim_s: float | None
    lane_targets: dict[str, float] = field(default_factory=dict)  # lane_id -> throttled speed


class OperatorAnomalyController:
    def __init__(self, impact_cfg: AnomalyImpactConfig | None = None):
        self.cfg = impact_cfg or AnomalyImpactConfig()
        self._active: dict[str, _Active] = {}
        # lane_id -> un-throttled max speed, captured once when the lane first gets
        # throttled and kept until no active anomaly touches it (overlap-safe)
        self._baseline: dict[str, float] = {}
        self._events: list[dict] = []
        self._last_republish_s = 0.0

    # ---- command handling ---------------------------------------------

    def handle_create(self, payload: Mapping, *, step: int, sim_time_s: float) -> None:
        anomaly_id = str(payload["anomaly_id"])
        if anomaly_id in self._active:
            log.warning("anomaly %s already active -- ignoring duplicate create", anomaly_id)
            return

        edge_id = str(payload["edge_id"])
        lane_id = payload.get("lane_id")
        sev_key = str(payload["severity"]).lower()
        atype = _TYPE_MAP.get(str(payload["anomaly_type"]), AnomalyType.UNKNOWN)
        severity = _SEV_MAP.get(str(payload["severity"]), AnomalySeverity.MEDIUM)
        duration_s = payload.get("duration_s")
        impact = self.cfg.estimated_impact.get(sev_key, 0.5)

        lanes = self._resolve_lanes(edge_id, lane_id)
        if not lanes:
            log.warning("anomaly %s: no lanes for edge %s -- skipping", anomaly_id, edge_id)
            return

        originals: dict[str, float] = {}
        targets: dict[str, float] = {}
        for lane in lanes:
            try:
                original = (
                    self._baseline[lane] if lane in self._baseline
                    else float(traci.lane.getMaxSpeed(lane))
                )
            except traci.TraCIException:
                log.warning("anomaly %s: lane %s not in the network -- skipping it",
                            anomaly_id, lane)
                continue
            originals[lane] = original
            target = (
                _BLOCK_SPEED_MPS
                if severity is AnomalySeverity.BLOCKED
                else max(_BLOCK_SPEED_MPS, original * self.cfg.speed_keep_frac.get(sev_key, 0.5))
            )
            self._baseline.setdefault(lane, original)
            targets[lane] = target
        if not originals:
            return

        anomaly = Anomaly.create(
            anomaly_id=anomaly_id,
            source=AnomalySource.OPERATOR,
            anomaly_type=atype,
            severity=severity,
            edge_id=edge_id,
            at_ms=epoch_ms(payload.get("requested_at"), sim_time_s * 1000),
            estimated_impact=impact,
            lane_id=str(lane_id) if lane_id else None,
            duration_s=float(duration_s) if duration_s else None,
            position_m=(
                float(payload["position_m"]) if payload.get("position_m") is not None else None
            ),
            detail=str(payload.get("detail", "")),
            operator=str(payload.get("operator", "operator:console")),
        )
        expire_at = None if not duration_s else sim_time_s + float(duration_s)
        self._active[anomaly_id] = _Active(anomaly, originals, expire_at, targets)
        for lane in targets:
            self._apply_lane(lane)
        log.info(
            "anomaly %s ACTIVE on %s (%s/%s) over %d lane(s), impact=%.2f",
            anomaly_id, edge_id, atype.value, severity.value, len(originals), impact,
        )
        self._queue_event(anomaly, step, sim_time_s)

    def handle_clear(self, payload: Mapping, *, step: int, sim_time_s: float) -> None:
        anomaly_id = str(payload["anomaly_id"])
        active = self._active.pop(anomaly_id, None)
        if active is None:
            log.warning("clear for unknown/expired anomaly %s -- ignoring", anomaly_id)
            return
        self._restore(active)
        resolution = str(payload.get("resolution", "RESOLVED"))
        reason = str(payload.get("reason", ""))
        at_ms = epoch_ms(payload.get("requested_at"), sim_time_s * 1000)
        anomaly = (
            active.anomaly.cancelled(at_ms=at_ms, reason=reason)
            if resolution == "CANCELLED"
            else active.anomaly.resolved(at_ms=at_ms, reason=reason)
        )
        log.info("anomaly %s %s by %s", anomaly_id, anomaly.status.value,
                 payload.get("operator", "?"))
        self._queue_event(anomaly, step, sim_time_s)

    # ---- per-tick ---------------------------------------------------

    def tick(self, step: int, sim_time_s: float) -> None:
        # auto-expire time-boxed anomalies
        expired = [
            aid for aid, a in self._active.items()
            if a.expire_at_sim_s is not None and sim_time_s >= a.expire_at_sim_s
        ]
        for aid in expired:
            active = self._active.pop(aid)
            self._restore(active)
            anomaly = active.anomaly.resolved(
                at_ms=int(sim_time_s * 1000), reason="duration elapsed"
            )
            log.info("anomaly %s auto-resolved (duration elapsed)", aid)
            self._queue_event(anomaly, step, sim_time_s)

        # periodic re-publish of everything still active, for late joiners
        if sim_time_s - self._last_republish_s >= self.cfg.republish_interval_s:
            self._last_republish_s = sim_time_s
            for active in self._active.values():
                self._queue_event(active.anomaly, step, sim_time_s)

    def drain_events(self) -> list[dict]:
        out, self._events = self._events, []
        return out

    def active_anomalies(self) -> list[Anomaly]:
        return [a.anomaly for a in self._active.values()]

    def restore_all(self) -> None:
        self._active.clear()
        for lane in list(self._baseline):
            self._apply_lane(lane)

    # ---- internals ----------------------------------------------

    @staticmethod
    def _resolve_lanes(edge_id: str, lane_id: str | None) -> list[str]:
        if lane_id:
            return [str(lane_id)]
        try:
            n = traci.edge.getLaneNumber(edge_id)
        except traci.TraCIException:
            return []
        return [f"{edge_id}_{i}" for i in range(n)]

    def _apply_lane(self, lane: str) -> None:
        """Set `lane` to the tightest limit among active anomalies, or back to its
        baseline (and forget it) when none remain. Callers pop the finished
        anomaly from `_active` first."""
        speeds = [a.lane_targets[lane] for a in self._active.values() if lane in a.lane_targets]
        value = min(speeds) if speeds else self._baseline.get(lane)
        if value is None:
            return
        try:
            traci.lane.setMaxSpeed(lane, value)
        except Exception:  # noqa: BLE001 -- connection already closed (FatalTraCIError)
            pass           # or the lane is gone; nothing left to restore either way
        if not speeds:
            self._baseline.pop(lane, None)

    def _restore(self, active: _Active) -> None:
        for lane in active.lane_originals:
            self._apply_lane(lane)

    def _queue_event(self, anomaly: Anomaly, step: int, sim_time_s: float) -> None:
        self._events.append(anomaly_updated_payload(anomaly, sim_tick=step))


def anomaly_updated_payload(anomaly: Anomaly, *, sim_tick: int | None = None) -> dict:
    """`Anomaly` -> AnomalyUpdated payload, matching anomaly_updated.avsc. A
    resolve/cancel reason (kept in metadata by the domain type) surfaces as
    `detail` so a client sees why an anomaly went terminal."""
    detail = anomaly.detail
    for key in ("resolved_reason", "cancelled_reason"):
        if key in anomaly.metadata:
            detail = anomaly.metadata[key]
    return {
        "anomaly_id": anomaly.anomaly_id,
        "source": anomaly.source.name,
        "anomaly_type": anomaly.anomaly_type.value,
        "severity": anomaly.severity.value,
        "status": anomaly.status.name,
        "edge_id": anomaly.edge_id,
        "lane_id": anomaly.lane_id,
        "estimated_impact": float(anomaly.estimated_impact),
        "position_m": anomaly.position_m,
        "start_time_ms": anomaly.start_time_ms,
        "expires_at_ms": anomaly.expires_at_ms(),
        "sim_tick": sim_tick,
        "detail": detail,
        "operator": anomaly.operator,
    }
