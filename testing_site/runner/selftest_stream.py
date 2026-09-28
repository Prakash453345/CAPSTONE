"""Site self-test: a synthetic event stream, with no SUMO and no controllers.

**This does not test your platform. It tests this site.**

It publishes correctly-shaped events -- encoded through the repo's own
`itms_common.events`, against the real `contracts/events/*.avsc` schemas, onto
the real Redis topics -- and drains `commands.operator`, answering an anomaly
or dispatch command the way the simulation would. So every screen lights up,
every command round-trips, and the incident human gate has something to act
on, all without SUMO.

Why it exists: when nothing appears on the map, the question is always "is it
my backend or is it the page?". Run this and you have the answer -- if the
screens fill in, the page and `api-service` are fine and the problem is in the
simulation; if they stay empty, the problem is between the browser, the bus and
`api-service`.

Nothing here is a model of traffic. The vehicles walk along the corridor's real
geometry at plausible speeds and the signals cycle on a timer; there is no
control logic, no safety kernel, no routing. Never read a KPI off a self-test
run -- the site never scores one, and runs started this way are not recorded in
the run history.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import signal
import sys
import time
import uuid
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parents[1]
CAPSTONE_DIR = SITE_DIR.parent
REPO = Path(os.environ.get("ITMS_REPO") or (CAPSTONE_DIR / "itms")).resolve()
for p in (REPO / "packages" / "common", REPO / "packages" / "domain"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

logging.basicConfig(level=logging.INFO, format="%(asctime)s selftest %(levelname)s %(message)s")
log = logging.getLogger("selftest")

GEOJSON = REPO / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.geojson"


def load_corridor() -> tuple[dict, list[str]]:
    data = json.loads(GEOJSON.read_text(encoding="utf-8"))
    edges, tls = {}, []
    for f in data["features"]:
        props = f["properties"]
        if props.get("kind") == "edge":
            edges[props["edge_id"]] = f["geometry"]["coordinates"]
        elif props.get("kind") == "junction" and props.get("is_traffic_light"):
            tls.append(props["junction_id"])
    return edges, tls


def interp(coords, t: float) -> tuple[float, float, float]:
    """Position and bearing a fraction `t` along a LineString."""
    if len(coords) < 2:
        lon, lat = coords[0]
        return lat, lon, 0.0
    segs = []
    total = 0.0
    for a, b in zip(coords, coords[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        segs.append((a, b, d))
        total += d
    target = max(0.0, min(1.0, t)) * total
    walked = 0.0
    for a, b, d in segs:
        if walked + d >= target or d == 0:
            f = 0.0 if d == 0 else (target - walked) / d
            lon = a[0] + (b[0] - a[0]) * f
            lat = a[1] + (b[1] - a[1]) * f
            bearing = (math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) + 360) % 360
            return lat, lon, bearing
        walked += d
    lon, lat = coords[-1]
    return lat, lon, 0.0


def route_summary(edges: dict, path: list[str], rank: int = 0) -> dict:
    dist = sum(len(edges[e]) * 60.0 for e in path)
    return {
        "edges": path,
        "rank": rank,
        "total_distance_m": dist,
        "total_travel_time_s": dist / 9.0,
        "eta_s": dist / 9.0 + 18.0 * rank + 24.0,
        "n_intersections": max(0, len(path) - 1),
        "signalised_intersections": [f"tls-{i}" for i in range(min(4, len(path) - 1))],
        "congested_segments": path[1:2],
        "anomalous_segments_avoided": [],
        "reliable": rank == 0,
        "cost_travel_time_s": dist / 9.0,
        "cost_congestion": 0.42 + rank * 0.1,
        "cost_anomaly": 0.0,
        "cost_signal_delay_s": 14.0 + rank * 4,
        "cost_disruption": dist / 400.0,
        "cost_reliability": 0.21 + rank * 0.2,
        "route_score": 3.1 + rank * 0.8,
        "weights_used": {
            "travel_time": 1.0, "congestion": 0.6, "anomaly": 1.0,
            "signal_delay": 0.4, "disruption": 0.5, "reliability": 0.3,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="synthetic event stream for site self-test")
    ap.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    ap.add_argument("--seconds", type=float, default=180.0)
    ap.add_argument("--vehicles", type=int, default=70)
    ap.add_argument("--status-file", default="")
    args = ap.parse_args()

    from itms_common.bus import RedisStreamsSyncBus, RedisStreamsSyncConsumer
    from itms_common.events import decode_envelope, encode_envelope

    edges, tls_ids = load_corridor()
    edge_ids = sorted(edges)
    if not edge_ids:
        log.error("no corridor geometry at %s", GEOJSON)
        return 2

    bus = RedisStreamsSyncBus(args.redis_url)
    consumer = RedisStreamsSyncConsumer(
        ["commands.operator"], group="selftest", consumer=f"selftest-{os.getpid()}",
        url=args.redis_url,
    )
    rng = random.Random(7)
    stop = {"flag": False}

    def _sig(*_):
        stop["flag"] = True
    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(s, _sig)
        except (ValueError, OSError):
            pass

    def pub(topic, event_type, payload, key=""):
        bus.publish(topic, encode_envelope(
            event_type=event_type, source="selftest", payload=payload, partition_key=key or None))

    vtypes = ["veh_car"] * 4 + ["veh_motorcycle"] * 3 + ["veh_auto"] * 2 + ["veh_bus"]
    fleet = [{
        "id": f"selftest_{i}",
        "edge": rng.choice(edge_ids),
        "t": rng.random(),
        "v": rng.uniform(0.02, 0.06),
        "type": rng.choice(vtypes),
    } for i in range(max(1, args.vehicles))]

    phases = ["P0", "P1", "P2"]
    sources = ["acamp"] * 8 + ["fixed_time"]
    anomalies: dict[str, dict] = {}
    requests: dict[str, dict] = {}
    step = 0
    t0 = time.monotonic()
    status_path = Path(args.status_file) if args.status_file else None

    log.info("publishing to %s for %.0fs (%d vehicles, %d signals)",
             args.redis_url, args.seconds, len(fleet), len(tls_ids))

    while not stop["flag"] and time.monotonic() - t0 < args.seconds:
        step += 1
        now_ms = int(time.time() * 1000)

        # --- operator commands, answered the way sim-service would ---------
        for msg in consumer.drain():
            try:
                env = decode_envelope(msg.raw)
            except Exception:
                consumer.ack(msg.topic, msg.message_id)
                continue
            etype, p = env.get("event_type"), env.get("payload", {})
            try:
                if etype == "AnomalyCreateRequested":
                    impact = {"LOW": 0.25, "MEDIUM": 0.5, "HIGH": 0.8, "BLOCKED": 1.0}
                    rec = {
                        "anomaly_id": p["anomaly_id"], "source": "OPERATOR",
                        "anomaly_type": str(p["anomaly_type"]).lower(),
                        "severity": str(p["severity"]).lower(), "status": "ACTIVE",
                        "edge_id": p["edge_id"], "lane_id": None,
                        "estimated_impact": impact.get(p["severity"], 0.5),
                        "position_m": None, "start_time_ms": now_ms,
                        "expires_at_ms": (now_ms + int(p["duration_s"] * 1000)) if p.get("duration_s") else None,
                        "sim_tick": step, "detail": "self-test acknowledgement",
                        "operator": p.get("operator", ""),
                    }
                    anomalies[rec["anomaly_id"]] = rec
                    pub("anomaly.updated", "AnomalyUpdated", rec, rec["edge_id"])
                    log.info("anomaly %s ACTIVE on %s", rec["anomaly_id"][:8], rec["edge_id"])
                elif etype == "AnomalyClearRequested":
                    rec = anomalies.get(p["anomaly_id"])
                    if rec:
                        rec["status"] = "RESOLVED" if p.get("resolution", "RESOLVED") == "RESOLVED" else "CANCELLED"
                        rec["detail"] = p.get("reason", "")
                        pub("anomaly.updated", "AnomalyUpdated", rec, rec["edge_id"])
                elif etype == "EmergencyRequestCreated":
                    src, dst = p["source_edge"], p["destination_edge"]
                    path = [src] + rng.sample(edge_ids, k=min(4, len(edge_ids))) + [dst]
                    rec = {
                        "request_id": p["request_id"], "vehicle_id": p["vehicle_id"],
                        "vehicle_kind": str(p.get("vehicle_kind", "AMBULANCE")).lower(),
                        "state": "ROUTE_READY", "source_edge": src, "destination_edge": dst,
                        "eta_s": 210.0, "green_corridor_id": None,
                        "route": route_summary(edges, path, 0),
                        "alternatives": [route_summary(edges, path[::-1], 1)],
                        "chain_hash": uuid.uuid4().hex, "actor": "system:router",
                        "detail": "self-test route (no real router ran)",
                        "sim_tick": step, "updated_at": now_ms,
                    }
                    requests[rec["request_id"]] = {"rec": rec, "path": path, "progress": 0.0, "corridor": None}
                    pub("emergency.request-updated", "EmergencyRequestUpdated", rec, rec["request_id"])
                    log.info("request %s ROUTE_READY", rec["request_id"][:8])
                elif etype == "EmergencyCommand":
                    entry = requests.get(p["request_id"])
                    action = str(p["action"])
                    if entry and action == "ACTIVATE_CORRIDOR":
                        cid = uuid.uuid4().hex
                        entry["corridor"] = cid
                        entry["rec"].update(state="GREEN_CORRIDOR_ACTIVE", green_corridor_id=cid,
                                            detail="corridor armed (self-test)", updated_at=now_ms,
                                            chain_hash=uuid.uuid4().hex, actor="operator:testlab")
                        pub("emergency.request-updated", "EmergencyRequestUpdated", entry["rec"], p["request_id"])
                        res = [{
                            "intersection_id": t, "movements": ["L0", "L1"],
                            "open_at_ms": now_ms + i * 12000, "close_at_ms": now_ms + i * 12000 + 19000,
                            "order": i,
                        } for i, t in enumerate(tls_ids[:4])]
                        pub("emergency.corridor-updated", "GreenCorridorUpdated", {
                            "corridor_id": cid, "request_id": p["request_id"],
                            "vehicle_id": entry["rec"]["vehicle_id"], "event": "activated",
                            "status": "ACTIVE", "route_edges": entry["path"], "reservations": res,
                            "peak_concurrency": 2, "detail": "self-test corridor",
                            "sim_tick": step, "updated_at": now_ms,
                        }, p["request_id"])
                        log.info("corridor %s ACTIVE", cid[:8])
                    elif entry and action == "CANCEL":
                        entry["rec"].update(state="CANCELLED", detail="cancelled (self-test)",
                                            updated_at=now_ms, chain_hash=uuid.uuid4().hex)
                        pub("emergency.request-updated", "EmergencyRequestUpdated", entry["rec"], p["request_id"])
                    elif entry and action == "RECALCULATE":
                        entry["rec"].update(detail="recalculated (self-test)", updated_at=now_ms,
                                            chain_hash=uuid.uuid4().hex, actor="operator:testlab")
                        pub("emergency.request-updated", "EmergencyRequestUpdated", entry["rec"], p["request_id"])
            except Exception:
                log.exception("could not answer command %s", etype)
            finally:
                consumer.ack(msg.topic, msg.message_id)

        # --- traffic ------------------------------------------------------
        blocked = {a["edge_id"] for a in anomalies.values() if a["status"] == "ACTIVE"}
        for v in fleet:
            slow = 0.18 if v["edge"] in blocked else 1.0
            v["t"] += v["v"] * slow
            if v["t"] >= 1.0:
                v["t"] = 0.0
                v["edge"] = rng.choice(edge_ids)
            lat, lon, bearing = interp(edges[v["edge"]], v["t"])
            pub("traffic.vehicle-positions", "VehiclePositionUpdated", {
                "vehicle_id": v["id"], "vehicle_type": v["type"], "lat": lat, "lon": lon,
                "speed_mps": round(v["v"] * 320 * slow, 2), "heading_deg": round(bearing, 1),
                "edge_id": v["edge"], "source": "selftest",
            }, v["edge"])

        counts: dict[str, int] = {}
        for v in fleet:
            counts[v["edge"]] = counts.get(v["edge"], 0) + 1
        for eid in edge_ids:
            n = counts.get(eid, 0)
            pub("traffic.updated", "ApproachState", {
                "movement_id": eid, "q_pcu": float(n),
                "occupancy": min(0.9, n / 12.0 + (0.35 if eid in blocked else 0.0)),
                "arrival_rate_pcu_s": n / 8.0, "queue_truncated": False,
                "confidence": 1.0, "model": "selftest", "source": "selftest",
            }, eid)

        # --- signals ------------------------------------------------------
        if step % 3 == 0 and tls_ids:
            corridor_on = any(e["corridor"] for e in requests.values())
            k = step // 3
            for offset in (0, 1):
                i = (k + offset) % len(tls_ids)
                pub("signal.changed", "SignalChanged", {
                    "intersection_id": tls_ids[i],
                    "phase_id": phases[(k + i) % len(phases)],
                    "source": "corridor_preemption" if (corridor_on and i < 3) else rng.choice(sources),
                }, tls_ids[i])
            if step % 90 == 0:
                # One fault, once, so the fault list and the failsafe rung are
                # exercised too -- an empty panel proves nothing.
                pub("signal.faulted", "SignalFaulted", {
                    "intersection_id": tls_ids[0],
                    "fault_type": "readback_divergence",
                    "detail": "synthetic fault from the site self-test",
                }, tls_ids[0])

        # --- emergency vehicles in transit --------------------------------
        for rid, entry in list(requests.items()):
            if not entry["corridor"] or entry["rec"]["state"] in ("COMPLETED", "CANCELLED"):
                continue
            entry["progress"] = min(1.0, entry["progress"] + 0.012)
            idx = min(len(entry["path"]) - 1, int(entry["progress"] * len(entry["path"])))
            lat, lon, _ = interp(edges[entry["path"][idx]], (entry["progress"] * len(entry["path"])) % 1.0)
            pub("emergency.vehicle-updated", "EmergencyVehicleUpdated", {
                "vehicle_id": entry["rec"]["vehicle_id"], "request_id": rid,
                "vehicle_kind": entry["rec"]["vehicle_kind"],
                "status": "ARRIVED" if entry["progress"] >= 1.0 else "EN_ROUTE",
                "lat": lat, "lon": lon, "edge_id": entry["path"][idx],
                "speed_mps": 12.4, "eta_s": max(0.0, 210 * (1 - entry["progress"])),
                "route_progress": entry["progress"], "sim_tick": step,
            }, entry["rec"]["vehicle_id"])
            if entry["rec"]["state"] == "GREEN_CORRIDOR_ACTIVE" and entry["progress"] > 0.05:
                entry["rec"].update(state="IN_TRANSIT", updated_at=now_ms,
                                    chain_hash=uuid.uuid4().hex, detail="departed (self-test)")
                pub("emergency.request-updated", "EmergencyRequestUpdated", entry["rec"], rid)
            if entry["progress"] >= 1.0:
                entry["rec"].update(state="COMPLETED", updated_at=now_ms,
                                    chain_hash=uuid.uuid4().hex, detail="arrived (self-test)")
                pub("emergency.request-updated", "EmergencyRequestUpdated", entry["rec"], rid)
                pub("emergency.corridor-updated", "GreenCorridorUpdated", {
                    "corridor_id": entry["corridor"], "request_id": rid,
                    "vehicle_id": entry["rec"]["vehicle_id"], "event": "terminated",
                    "status": "COMPLETED", "route_edges": entry["path"], "reservations": [],
                    "peak_concurrency": 2, "detail": "all junctions cleared (self-test)",
                    "sim_tick": step, "updated_at": now_ms,
                }, rid)

        # --- one incident candidate, so the human gate has something ------
        if step == 25:
            pub("incident.candidate", "IncidentCandidate", {
                "incident_id": str(uuid.uuid4()),
                "detected_at": now_ms, "sim_tick": step,
                "intersection_id": tls_ids[0] if tls_ids else "unknown",
                "link_id": "L2", "graph_score": 4.12, "vision_score": None,
                "fused_probability": 0.91, "threshold_tau": 0.78,
                "false_alarm_budget": 0.05,
                "detector_version": "SELF-TEST-NOT-A-REAL-DETECTOR",
            }, tls_ids[0] if tls_ids else "unknown")
            log.info("published one synthetic incident candidate")

        # The real controller republishes each active anomaly every 10 s so a
        # client that connects late converges. Mirrored here for the same
        # reason -- otherwise a page opened after an injection shows nothing.
        if step % 10 == 0:
            for rec in anomalies.values():
                if rec["status"] == "ACTIVE":
                    pub("anomaly.updated", "AnomalyUpdated", rec, rec["edge_id"])
            pub("system.heartbeat", "SystemHeartbeat",
                {"service": "selftest", "seq": step // 10, "message": "synthetic"}, "selftest")

        if status_path and step % 2 == 0:
            tmp = status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "state": "running", "engine": "selftest", "demand": "synthetic",
                "controller": "none (synthetic stream)", "step": step,
                "sim_time_s": round(time.monotonic() - t0, 1),
                "wall_s": round(time.monotonic() - t0, 1), "steps_per_s": 1.0,
                "note": "SELF-TEST: synthetic events, no SUMO and no control logic. "
                        "Never read a KPI from this.",
                "vehicles": {"active": len(fleet), "departed_total": len(fleet),
                             "arrived_total": 0, "teleports": 0},
                "updated_at": time.time(),
            }), encoding="utf-8")
            tmp.replace(status_path)

        time.sleep(1.0)

    if status_path:
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            data["state"] = "finished"
            status_path.write_text(json.dumps(data), encoding="utf-8")
        except (OSError, ValueError):
            pass
    consumer.close()
    bus.close()
    log.info("self-test stream finished after %d steps", step)
    return 0


if __name__ == "__main__":
    sys.exit(main())
