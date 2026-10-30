"""End-to-end smoke for the emergency / green-corridor path (Phase 6).

Needs Redis + SUMO. Unit coverage is `test_green_corridor.py`,
`test_emergency_corridor.py`, `test_arbiter_preemption.py`,
`test_emergency_control.py`.

Flow exercised:
    pre-create the `sim-service-live` consumer group
    -> publish EmergencyRequestCreated + EmergencyCommand(ACTIVATE_CORRIDOR)
       on `commands.operator` (same tick: create routes synchronously to
       ROUTE_READY, then the corridor arms and the vehicle is spawned)
    -> run_live(max_steps=N): the arbiter takes `corridor_preemption`
       decisions at the junctions the EV crosses; the EV drives to its
       destination and the request completes
    -> read the streams back and assert:
         * an EmergencyRequestUpdated reached GREEN_CORRIDOR_ACTIVE or beyond
         * a GreenCorridorUpdated with status ACTIVE and >= 1 reservation
         * >= 1 signal.changed with source == "corridor_preemption"
         * an EmergencyVehicleUpdated with route_progress > 0

Usage:  python scripts/smoke_live_corridor.py [demand]   (light | medium | heavy)
"""

from __future__ import annotations

import sys
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
CORRIDOR_TOPIC = "emergency.corridor-updated"
VEHICLE_TOPIC = "emergency.vehicle-updated"
SIGNAL_TOPIC = "signal.changed"
MAX_STEPS = 240


def _pick_route() -> tuple[str, str]:
    """First (source, destination) whose optimal route crosses >= 1 signal."""
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
            if routes and routes[0].signalised_intersections and len(routes[0].edges) >= 3:
                return src, dst
    raise SystemExit("no signalised route found in the corridor network")


def _read(r: redis_sync.Redis, topic: str, since: int) -> list[dict]:
    if not r.exists(topic):
        return []
    return [
        decode_envelope(fields[b"raw"])["payload"]
        for _, fields in r.xrange(topic, min="-", max="+")[since:]
    ]


def main() -> None:
    demand = sys.argv[1] if len(sys.argv) > 1 else "light"
    src, dst = _pick_route()
    request_id = str(uuid.uuid4())
    r = redis_sync.from_url(REDIS_URL)

    marks = {t: (r.xlen(t) if r.exists(t) else 0) for t in
             (REQUEST_TOPIC, CORRIDOR_TOPIC, VEHICLE_TOPIC, SIGNAL_TOPIC)}

    RedisStreamsSyncConsumer([COMMANDS_TOPIC], group=CONSUMER_GROUP, consumer="smoke",
                             url=REDIS_URL).close()

    bus = RedisStreamsSyncBus(REDIS_URL)
    now_ms = int(time.time() * 1000)
    bus.publish(COMMANDS_TOPIC, encode_envelope(
        event_type="EmergencyRequestCreated", source="smoke",
        payload={
            "request_id": request_id, "vehicle_id": "amb-smoke",
            "vehicle_kind": "AMBULANCE", "source_edge": src, "destination_edge": dst,
            "priority": 1, "operator": "operator:smoke", "requested_at": now_ms,
        },
    ))
    bus.publish(COMMANDS_TOPIC, encode_envelope(
        event_type="EmergencyCommand", source="smoke",
        payload={
            "request_id": request_id, "action": "ACTIVATE_CORRIDOR",
            "reason": "smoke", "operator": "operator:smoke", "requested_at": now_ms,
        },
    ))
    bus.close()
    print(f"published EmergencyRequestCreated + ACTIVATE_CORRIDOR  {src} -> {dst}")

    summary = run_live(
        redis_url=REDIS_URL, demand=demand, realtime_factor=1e6, max_steps=MAX_STEPS
    )
    print(f"run_live: {summary}")

    requests = [p for p in _read(r, REQUEST_TOPIC, marks[REQUEST_TOPIC])
                if p["request_id"] == request_id]
    corridors = [p for p in _read(r, CORRIDOR_TOPIC, marks[CORRIDOR_TOPIC])
                 if p["request_id"] == request_id]
    vehicles = [p for p in _read(r, VEHICLE_TOPIC, marks[VEHICLE_TOPIC])
                if p["request_id"] == request_id]
    preemptions = [p for p in _read(r, SIGNAL_TOPIC, marks[SIGNAL_TOPIC])
                   if p.get("source") == "corridor_preemption"]

    states = [p["state"] for p in requests]
    active_corridor = [p for p in corridors if p["status"] == "ACTIVE" and p["reservations"]]
    moved = [p for p in vehicles if p["route_progress"] > 0]

    ok = (
        any(s in ("GREEN_CORRIDOR_ACTIVE", "IN_TRANSIT", "COMPLETED") for s in states)
        and active_corridor
        and preemptions
        and moved
    )
    print(f"\nrequest states seen   : {states}")
    print(f"corridor events       : {[p['event'] for p in corridors]}")
    print(f"corridor_preemption signal.changed : {len(preemptions)}")
    print(f"vehicle updates moving : {len(moved)} / {len(vehicles)}")
    print(f"\n{'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
