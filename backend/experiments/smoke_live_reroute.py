"""End-to-end smoke for automatic rerouting (Phase 7) against a running
simulation. Needs Redis + SUMO.

Unlike `smoke_live_corridor.py`, this one injects the BLOCKED anomaly *after*
the ambulance has departed: `run_live` runs on a background thread while the
main thread waits, then publishes an `AnomalyCreateRequested` (BLOCKED) on an
edge that is still ahead on the route. It then reads `emergency.request-updated`
back and asserts the request rerouted (or, if there is no alternative, cleanly
held its route -- both are correct behaviour and both prove the monitor fired).

Usage:  python scripts/smoke_live_reroute.py [demand]
"""

from __future__ import annotations

import sys
import threading
import time
import uuid
from pathlib import Path

import redis as redis_sync
from itms_common.bus import RedisStreamsSyncBus, RedisStreamsSyncConsumer
from itms_common.events import decode_envelope, encode_envelope

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "services" / "simulation-service"))

from sim_service.live.corridor import NET_PATH  # noqa: E402
from sim_service.live.service import CONSUMER_GROUP, run_live  # noqa: E402
from sim_service.routing import RoadGraph, RoutePlanner  # noqa: E402

REDIS_URL = "redis://localhost:6379/0"
COMMANDS_TOPIC = "commands.operator"
REQUEST_TOPIC = "emergency.request-updated"
REALTIME_FACTOR = 6.0
MAX_STEPS = 360
INJECT_AFTER_WALL_S = 6.0


def _pick_route() -> tuple[str, str, list[str]]:
    graph = RoadGraph.from_network(NET_PATH)
    planner = RoutePlanner(graph)
    edges = list(graph.edges)
    for src in edges:
        for dst in edges:
            if src == dst:
                continue
            try:
                routes = planner.plan(src, dst)
            except Exception:  # noqa: BLE001
                continue
            if routes and len(routes[0].edges) >= 5:
                return src, dst, list(routes[0].edges)
    raise SystemExit("no long-enough route found")


def _read(r: redis_sync.Redis, topic: str, since: int) -> list[dict]:
    if not r.exists(topic):
        return []
    return [
        decode_envelope(fields[b"raw"])["payload"]
        for _, fields in r.xrange(topic, min="-", max="+")[since:]
    ]


def main() -> None:
    demand = sys.argv[1] if len(sys.argv) > 1 else "light"
    src, dst, route_edges = _pick_route()
    blocked_edge = route_edges[len(route_edges) - 2]  # last hop before the destination
    request_id = str(uuid.uuid4())
    anomaly_id = str(uuid.uuid4())
    r = redis_sync.from_url(REDIS_URL)
    mark = r.xlen(REQUEST_TOPIC) if r.exists(REQUEST_TOPIC) else 0

    RedisStreamsSyncConsumer([COMMANDS_TOPIC], group=CONSUMER_GROUP, consumer="smoke",
                             url=REDIS_URL).close()

    bus = RedisStreamsSyncBus(REDIS_URL)
    now_ms = int(time.time() * 1000)
    bus.publish(COMMANDS_TOPIC, encode_envelope(
        event_type="EmergencyRequestCreated", source="smoke",
        payload={"request_id": request_id, "vehicle_id": "amb-smoke",
                 "vehicle_kind": "AMBULANCE", "source_edge": src, "destination_edge": dst,
                 "priority": 1, "operator": "operator:smoke", "requested_at": now_ms}))
    bus.publish(COMMANDS_TOPIC, encode_envelope(
        event_type="EmergencyCommand", source="smoke",
        payload={"request_id": request_id, "action": "ACTIVATE_CORRIDOR",
                 "reason": "smoke", "operator": "operator:smoke", "requested_at": now_ms}))
    print(f"dispatched {src} -> {dst}; will block {blocked_edge} mid-run")

    summary: dict = {}

    def _run() -> None:
        summary.update(run_live(redis_url=REDIS_URL, demand=demand,
                                realtime_factor=REALTIME_FACTOR, max_steps=MAX_STEPS))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(INJECT_AFTER_WALL_S)

    inject_bus = RedisStreamsSyncBus(REDIS_URL)
    inject_bus.publish(COMMANDS_TOPIC, encode_envelope(
        event_type="AnomalyCreateRequested", source="smoke",
        payload={"anomaly_id": anomaly_id, "edge_id": blocked_edge, "lane_id": None,
                 "anomaly_type": "LANE_BLOCKAGE", "severity": "BLOCKED",
                 "duration_s": None, "position_m": None, "operator": "operator:smoke",
                 "requested_at": int(time.time() * 1000)}))
    inject_bus.close()
    print(f"injected BLOCKED anomaly on {blocked_edge} at ~{INJECT_AFTER_WALL_S}s wall")

    t.join(timeout=120)
    bus.close()
    print(f"run_live: {summary}")

    reqs = [p for p in _read(r, REQUEST_TOPIC, mark) if p["request_id"] == request_id]
    details = [p.get("detail", "") for p in reqs if p.get("detail")]
    reroute_details = [d for d in details if "reroute" in d.lower()]
    routes_seen = {tuple(p["route"]["edges"]) for p in reqs if p.get("route")}
    states = [p["state"] for p in reqs]

    monitor_fired = bool(reroute_details)
    route_changed = len(routes_seen) > 1
    ok = monitor_fired and (route_changed or any("held" in d for d in reroute_details))

    print(f"\nstates            : {states}")
    print(f"distinct routes   : {len(routes_seen)}")
    print(f"reroute detail(s) : {reroute_details}")
    print(f"\n{'PASS' if ok else 'FAIL'}  "
          f"(monitor fired={monitor_fired}, route changed={route_changed})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
