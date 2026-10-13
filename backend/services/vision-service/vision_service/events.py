"""Payload builders for everything the vision service publishes. Shapes
match `contracts/events/*.avsc` field for field; encoding is
`itms_common.events.encode_envelope`'s job, never done here.

Topics:

    vision.link-state      LinkStateEstimated, one per junction per tick
    vision.camera-status   CameraStatus, on change and while not OK
    anomaly.updated        AnomalyUpdated with source=VISION (existing topic)
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping

from vision_service.fire.monitor import FireCandidate
from vision_service.health import CameraHealth, CameraStatus
from vision_service.incidents.rules import AnomalyCandidate
from vision_service.state.estimator import LinkEstimate

LINK_STATE_TOPIC = "vision.link-state"
CAMERA_STATUS_TOPIC = "vision.camera-status"
ANOMALY_TOPIC = "anomaly.updated"
SOURCE = "vision-service"


def link_state_payload(
    tls_id: str,
    links: Mapping[tuple[str, str], LinkEstimate],
    vision_scores: Mapping[tuple[str, str], float],
    *,
    sim_time_s: float | None = None,
    model: str = "vision-m8",
) -> dict:
    rows = []
    for (tls, link), e in sorted(links.items()):
        if tls != tls_id:
            continue
        rows.append({
            "link_id": link,
            "queue_pcu": float(e.queue_pcu),
            "approaching_pcu": float(e.approaching_pcu),
            "receiving_occupancy": float(e.receiving_occupancy),
            "receiving_queue_pcu": float(e.receiving_queue_pcu),
            "confidence": float(e.confidence),
            "c_coverage": float(e.c_coverage),
            "c_health": float(e.c_health),
            "c_visibility": float(e.c_visibility),
            "c_truncation": float(e.c_truncation),
            "queue_truncated": bool(e.truncated),
            "hidden_queue_m": float(e.hidden_m),
            "vision_score": float(vision_scores.get((tls, link), 0.0)),
            "vehicles_seen": int(e.vehicles_seen),
            "cameras": list(e.cameras),
        })
    return {"intersection_id": tls_id, "sim_time_s": sim_time_s, "links": rows, "model": model}


def camera_status_payload(
    camera_id: str,
    status: tuple[CameraStatus, float, list[str]],
    health: CameraHealth | None = None,
    *,
    intersection_id: str | None = None,
    lonlat: tuple[float, float] | None = None,
    heading_deg: float | None = None,
) -> dict:
    st, score, reasons = status
    px = health.pixels.last if health is not None and health.pixels is not None else None
    drift = health.drift if health is not None else None

    def finite(v):
        return None if v is None or v != v else float(v)

    return {
        "camera_id": camera_id,
        "intersection_id": intersection_id,
        "status": str(st),
        "health_score": float(score),
        "reasons": list(reasons),
        "sharpness": finite(px.sharpness) if px is not None else None,
        "brightness": finite(px.brightness) if px is not None else None,
        "frozen_frames": int(px.frozen_frames) if px is not None else None,
        "drift_heading_err_deg": finite(drift.heading_err_deg) if drift is not None else None,
        "drift_offlane_rate": finite(drift.offlane_rate) if drift is not None else None,
        "lat": lonlat[1] if lonlat is not None else None,
        "lon": lonlat[0] if lonlat is not None else None,
        "heading_deg": heading_deg,
    }


def anomaly_payload(
    cand: AnomalyCandidate,
    *,
    n_lanes_on_edge: int,
    start_time_ms: int | None = None,
    sim_tick: int | None = None,
) -> dict:
    """A vision candidate as an `AnomalyUpdated` with `source = VISION`.
    `estimated_impact` is the share of the edge's lanes it blocks -- one lane
    of a three-lane approach is a third of its capacity."""
    status = "RESOLVED" if cand.status == "RESOLVED" else "ACTIVE"
    detail = {"rule": cand.rule, "score": round(cand.score, 3),
              "links": [f"{t}/{lk}" for t, lk in cand.links],
              **{k: v for k, v in cand.evidence.items() if k != "truth_id"}}
    return {
        "anomaly_id": cand.anomaly_id,
        "source": "VISION",
        "anomaly_type": cand.anomaly_type,
        "severity": cand.severity,
        "status": status,
        "edge_id": cand.edge_id,
        "lane_id": cand.lane_id or None,
        "estimated_impact": 1.0 / max(1, n_lanes_on_edge),
        "position_m": float(cand.position_m),
        "start_time_ms": start_time_ms if start_time_ms is not None else int(time.time() * 1000),
        "expires_at_ms": None,
        "sim_tick": sim_tick,
        "detail": json.dumps(detail, default=str)[:2000],
        "operator": "",
    }


def fire_payload(
    cand: FireCandidate,
    *,
    edge_id: str,
    start_time_ms: int | None = None,
) -> dict:
    """A fire/smoke candidate as an `AnomalyUpdated` with `source = VISION`.

    `anomaly_type` is "fire" (`itms_domain.anomaly.AnomalyType.FIRE`; the
    console has its word, and sim-service's incident response pages a fire
    truck and police for it once an anomaly of that type exists there).
    `estimated_impact` is 0: an unconfirmed
    candidate must not change routing; the operator sets the real impact when
    confirming (ADR-006). The box is normalised to the frame so a console can
    draw it without knowing the frame size."""
    detail = {"rule": "fire_smoke", "camera": cand.camera_id, "kind": cand.kind,
              "score": round(cand.score, 3), **cand.evidence}
    return {
        "anomaly_id": cand.candidate_id,
        "source": "VISION",
        "anomaly_type": "fire",
        "severity": "high",
        "status": "RESOLVED" if cand.status == "RESOLVED" else "ACTIVE",
        "edge_id": edge_id,
        "lane_id": None,
        "estimated_impact": 0.0,
        "position_m": None,
        "start_time_ms": start_time_ms if start_time_ms is not None else int(time.time() * 1000),
        "expires_at_ms": None,
        "sim_tick": None,
        "detail": json.dumps(detail, default=str)[:2000],
        "operator": "",
    }
