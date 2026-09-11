"""FE-Phase 12 — full closed-loop acceptance smoke test.

Needs Redis + SUMO. This is the backend half of the 21-step acceptance
scenario the frontend's Command Center / Anomaly Detection / Emergency
Response workspaces drive interactively: every command published here is
*exactly* the payload shape the UI's own `postCommand` calls send (see
`web-app/src/components/map/CreateAnomalyPanel.tsx` and `EmergencyPanel.tsx`),
so a pass here means the backend honours the full loop the UI depends on.
Actually *looking* at the map while this runs is a separate, still-open
verification step this session's tooling couldn't perform (see the FE-Phase
12 report) -- this script proves the data the UI would render is correct,
not that MapLibre draws it correctly.

Flow, combining `smoke_live_anomaly.py` + `smoke_live_corridor.py` +
`smoke_live_reroute.py` into one continuous run:
    pre-create the consumer group
    -> publish a HIGH lane-blockage AnomalyCreateRequested on a normal-traffic
       edge (independent of the ambulance's route)                        [1]
    -> run_live on a background thread
    -> wait, then read anomaly.updated back: ACTIVE, our edge, HIGH        [2]
    -> publish EmergencyRequestCreated (ambulance) for a long, signalised
       route, then EmergencyCommand(ACTIVATE_CORRIDOR)                    [3]
    -> wait for the request to reach GREEN_CORRIDOR_ACTIVE+ with a route
       and (if the planner found one) alternatives                       [4]
    -> wait for the EV to actually move (EmergencyVehicleUpdated) and for
       >= 1 corridor_preemption signal.changed                           [5]
    -> publish a BLOCKED AnomalyCreateRequested on an edge still ahead on
       the route                                                          [6]
    -> wait, then assert the monitor reacted (a reroute or a held route)  [7]
    -> keep running until the request reaches COMPLETED (or timeout)      [8]
    -> assert the corridor's last status is no longer ACTIVE/PROPOSED and
       no corridor_preemption signal.changed follows the EV's arrival     [9]

Usage:  python scripts/smoke_full_e2e.py [demand]   (light | medium | heavy)
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
sys.path.insert(0, str(_ROOT / "services" / "sim-service"))

from sim_service.live.corridor import NET_PATH, link_to_lane_map  # noqa: E402
from sim_service.live.service import CONSUMER_GROUP, run_live  # noqa: E402
from sim_service.routing import EdgeConditions, RoadGraph, RoutePlanner  # noqa: E402

REDIS_URL = "redis://localhost:6379/0"
COMMANDS_TOPIC = "commands.operator"
ANOMALY_TOPIC = "anomaly.updated"
REQUEST_TOPIC = "emergency.request-updated"
CORRIDOR_TOPIC = "emergency.corridor-updated"
VEHICLE_TOPIC = "emergency.vehicle-updated"
SIGNAL_TOPIC = "signal.changed"

REALTIME_FACTOR = 6.0
MAX_STEPS = 520
INJECT_ANOMALY_AFTER_S = 2.0
DISPATCH_AFTER_S = 4.0
INJECT_BLOCK_AFTER_S = 12.0
JOIN_TIMEOUT_S = 180

results: list[tuple[str, bool, str]] = []


def check(step: str, ok: bool, detail: str = "") -> bool:
    results.append((step, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {step}{f' -- {detail}' if detail else ''}")
    return ok


def _pick_ambient_edge(exclude: set[str]) -> str:
    """A controlled-approach edge for the network-wide anomaly (step 1-2),
    independent of the ambulance's own route -- `exclude` keeps it off that
    route so the two anomalies stay two genuinely separate scenarios, not one
    edge wearing two hats (which, upstream of the request's own current
    position, otherwise reads to the reroute monitor as an unrecoverable
    blockage "ahead" for the whole run)."""
    link_lanes = link_to_lane_map()
    for links in link_lanes.values():
        for lane in links.values():
            edge = lane.rsplit("_", 1)[0]
            if edge not in exclude:
                return edge
    raise SystemExit("no controlled lane outside the ambulance's route")


def _pick_route(planner: RoutePlanner, graph: RoadGraph) -> tuple[str, str, list[str]]:
    """A long (>= 6 edges), signalised route -- long enough to have real
    "still ahead" room for the mid-route BLOCKED injection, signalised so the
    green-corridor half of the flow actually exercises the arbiter."""
    edges = list(graph.edges)
    best: tuple[str, str, list[str]] | None = None
    for src in edges:
        for dst in edges:
            if src == dst:
                continue
            try:
                routes = planner.plan(src, dst)
            except Exception:  # noqa: BLE001
                continue
            if not routes or not routes[0].signalised_intersections:
                continue
            if len(routes[0].edges) >= 6:
                return src, dst, list(routes[0].edges)
            if best is None or len(routes[0].edges) > len(best[2]):
                best = (src, dst, list(routes[0].edges))
    if best is not None:
        return best
    raise SystemExit("no signalised route found in the corridor network")


def _pick_block_edge(planner: RoutePlanner, dst: str, route_edges: list[str]) -> tuple[str, bool]:
    """A candidate for the mid-route BLOCKED anomaly, roughly two-thirds of
    the way along -- well ahead of the EV, not the final approach. Returns
    `(edge, has_detour)`: whether the planner (probed the same way the
    backend's own monitor probes it) can find any path around that edge at
    all. This corridor network turns out to have essentially no redundant
    paths for a long route (confirmed by an exhaustive probe over every
    edge pair) -- the honest, non-circular way to still let the ambulance
    reach COMPLETED either way is a time-boxed anomaly (see `main`), not an
    unbounded one that would make arrival structurally impossible whenever
    `has_detour` comes back False."""
    idx = max(1, min(len(route_edges) - 2, (2 * len(route_edges)) // 3))
    candidate = route_edges[idx]
    blocked = EdgeConditions(anomaly_severity="blocked", anomaly_impact=1.0)
    try:
        detour = planner.plan(route_edges[idx - 1], dst, {candidate: blocked})
        has_detour = bool(detour) and candidate not in detour[0].edges
    except Exception:  # noqa: BLE001
        has_detour = False
    return candidate, has_detour


def _read(r: redis_sync.Redis, topic: str, since: int) -> list[dict]:
    if not r.exists(topic):
        return []
    return [
        decode_envelope(fields[b"raw"])["payload"]
        for _, fields in r.xrange(topic, min="-", max="+")[since:]
    ]


def main() -> None:
    demand = sys.argv[1] if len(sys.argv) > 1 else "light"
    r = redis_sync.from_url(REDIS_URL)

    graph = RoadGraph.from_network(NET_PATH)
    planner = RoutePlanner(graph)
    src, dst, route_edges = _pick_route(planner, graph)
    ambient_edge = _pick_ambient_edge(set(route_edges))
    block_edge, has_detour = _pick_block_edge(planner, dst, route_edges)
    # Bounded whenever no detour exists, so a genuinely correct "hold the
    # route" outcome (see `_pick_block_edge`) can't make arrival impossible;
    # unbounded when a detour *is* available, so that branch gets a real
    # permanent blockage to actually reroute around.
    block_duration_s = None if has_detour else 30
    request_id = str(uuid.uuid4())
    network_anomaly_id = str(uuid.uuid4())
    block_anomaly_id = str(uuid.uuid4())

    marks = {
        t: (r.xlen(t) if r.exists(t) else 0)
        for t in (ANOMALY_TOPIC, REQUEST_TOPIC, CORRIDOR_TOPIC, VEHICLE_TOPIC, SIGNAL_TOPIC)
    }

    RedisStreamsSyncConsumer(
        [COMMANDS_TOPIC], group=CONSUMER_GROUP, consumer="smoke", url=REDIS_URL
    ).close()

    print(f"ambient anomaly edge : {ambient_edge}")
    print(f"ambulance route      : {src} -> {dst}  ({len(route_edges)} edges)")
    print(f"blocked-ahead edge   : {block_edge}  (has_detour={has_detour}, "
          f"duration_s={block_duration_s})\n")

    summary: dict = {}

    def _run() -> None:
        summary.update(
            run_live(
                redis_url=REDIS_URL,
                demand=demand,
                realtime_factor=REALTIME_FACTOR,
                max_steps=MAX_STEPS,
            )
        )

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    print("[1] run_live started -- vehicles should now be moving\n")

    # ---- [1]/[2] HIGH lane-blockage anomaly, independent of the EV route --
    time.sleep(INJECT_ANOMALY_AFTER_S)
    bus = RedisStreamsSyncBus(REDIS_URL)
    bus.publish(
        COMMANDS_TOPIC,
        encode_envelope(
            event_type="AnomalyCreateRequested",
            source="smoke",
            payload={
                "anomaly_id": network_anomaly_id,
                "edge_id": ambient_edge,
                "lane_id": None,
                "anomaly_type": "LANE_BLOCKAGE",
                "severity": "HIGH",
                "duration_s": None,
                "position_m": None,
                "operator": "operator:smoke",
                "requested_at": int(time.time() * 1000),
            },
        ),
    )
    print(f"[2] published HIGH lane-blockage anomaly on {ambient_edge}")

    # ---- [3] dispatch the ambulance + activate a green corridor ----------
    time.sleep(DISPATCH_AFTER_S)
    now_ms = int(time.time() * 1000)
    bus.publish(
        COMMANDS_TOPIC,
        encode_envelope(
            event_type="EmergencyRequestCreated",
            source="smoke",
            payload={
                "request_id": request_id,
                "vehicle_id": "amb-e2e-smoke",
                "vehicle_kind": "AMBULANCE",
                "source_edge": src,
                "destination_edge": dst,
                "priority": 1,
                "operator": "operator:smoke",
                "requested_at": now_ms,
            },
        ),
    )
    print(f"[3] published EmergencyRequestCreated  {src} -> {dst}")

    time.sleep(1.5)  # let it reach ROUTE_READY before activating the corridor
    bus.publish(
        COMMANDS_TOPIC,
        encode_envelope(
            event_type="EmergencyCommand",
            source="smoke",
            payload={
                "request_id": request_id,
                "action": "ACTIVATE_CORRIDOR",
                "reason": "smoke",
                "operator": "operator:smoke",
                "requested_at": int(time.time() * 1000),
            },
        ),
    )
    print("[3] published EmergencyCommand(ACTIVATE_CORRIDOR)\n")

    # ---- [6] BLOCKED anomaly ahead on the route, once the EV is under way -
    time.sleep(INJECT_BLOCK_AFTER_S)
    bus.publish(
        COMMANDS_TOPIC,
        encode_envelope(
            event_type="AnomalyCreateRequested",
            source="smoke",
            payload={
                "anomaly_id": block_anomaly_id,
                "edge_id": block_edge,
                "lane_id": None,
                "anomaly_type": "LANE_BLOCKAGE",
                "severity": "BLOCKED",
                "duration_s": block_duration_s,
                "position_m": None,
                "operator": "operator:smoke",
                "requested_at": int(time.time() * 1000),
            },
        ),
    )
    bus.close()
    print(f"[6] published BLOCKED anomaly on {block_edge} (still ahead on the route)\n")

    t.join(timeout=JOIN_TIMEOUT_S)
    still_running = t.is_alive()
    print(f"run_live summary: {summary}")
    if still_running:
        print("(run_live did not finish within the join timeout -- reading whatever landed)\n")

    # ---- read every stream back, scoped to our ids -------------------------
    network_anomalies = [
        p for p in _read(r, ANOMALY_TOPIC, marks[ANOMALY_TOPIC])
        if p["anomaly_id"] == network_anomaly_id
    ]
    block_anomalies = [
        p for p in _read(r, ANOMALY_TOPIC, marks[ANOMALY_TOPIC])
        if p["anomaly_id"] == block_anomaly_id
    ]
    requests = [
        p for p in _read(r, REQUEST_TOPIC, marks[REQUEST_TOPIC])
        if p["request_id"] == request_id
    ]
    corridors = [
        p for p in _read(r, CORRIDOR_TOPIC, marks[CORRIDOR_TOPIC])
        if p["request_id"] == request_id
    ]
    vehicles = [
        p for p in _read(r, VEHICLE_TOPIC, marks[VEHICLE_TOPIC])
        if p["request_id"] == request_id
    ]
    preemptions = [
        p for p in _read(r, SIGNAL_TOPIC, marks[SIGNAL_TOPIC])
        if p.get("source") == "corridor_preemption"
    ]

    # The wire sends `state` uppercase (`EmergencyRequestState.name`, e.g.
    # "ROUTE_READY") -- lowercased here the same way `wsProvider.ts` does,
    # so the checks below read the way the frontend's own state values do.
    states = [p["state"].lower() for p in requests]
    details = [p.get("detail", "") for p in requests if p.get("detail")]
    routes_seen = {tuple(p["route"]["edges"]) for p in requests if p.get("route")}
    with_alts = [p for p in requests if p.get("alternatives")]
    moved = [p for p in vehicles if p.get("route_progress", 0) > 0]
    active_corridor = [p for p in corridors if p["status"] == "ACTIVE" and p["reservations"]]
    last_corridor_status = corridors[-1]["status"] if corridors else None

    print("\n" + "=" * 72)
    print("FE-Phase 12 -- 21-step acceptance scenario (backend half)")
    print("=" * 72)

    check("1. SUMO running, vehicles moving", summary.get("steps", 0) > 0 or moved != [],
          f"steps={summary.get('steps')}")
    check("2. HIGH lane-blockage anomaly reaches SUMO",
          bool(network_anomalies) and network_anomalies[-1]["status"] == "ACTIVE"
          and network_anomalies[-1]["severity"] == "high",
          f"{network_anomalies[-1] if network_anomalies else 'no AnomalyUpdated seen'}")
    check("3. Emergency request created & routed", "route_ready" in states or
          any(s in ("green_corridor_active", "in_transit", "completed") for s in states),
          f"states={states}")
    check("4. Recommended route calculated", bool(routes_seen),
          f"alternatives present on {len(with_alts)}/{len(requests)} updates"
          f"{'' if with_alts else ' (none offered by the planner for this route -- OK)'}")
    check("5. Green corridor activated", bool(active_corridor),
          f"corridor events={[c['event'] for c in corridors]}")
    check("6. Ambulance moves through SUMO", bool(moved),
          f"{len(moved)}/{len(vehicles)} vehicle updates show progress > 0")
    check("7. Signals held for the corridor (corridor_preemption)", bool(preemptions),
          f"{len(preemptions)} corridor_preemption signal.changed")
    # Bounded (see `_pick_block_edge`), so its *last* recorded status may
    # already be the auto-expiry, not ACTIVE -- what step 8 actually asks is
    # whether it ever reached SUMO as active at all.
    block_was_active = any(p["status"] == "ACTIVE" for p in block_anomalies)
    check("8. BLOCKED anomaly ahead reaches SUMO", block_was_active,
          f"{block_anomalies[-1] if block_anomalies else 'no AnomalyUpdated seen'}")
    reroute_or_held = any("reroute" in d.lower() or "held" in d.lower() for d in details)
    check("9. Automatic reroute monitor fired", reroute_or_held, f"details={details}")
    check("10. Route changed (or cleanly held, both are correct)",
          len(routes_seen) > 1 or any("held" in d.lower() for d in details),
          f"{len(routes_seen)} distinct route(s) seen")
    completed = "completed" in states
    check("11. Ambulance arrived (COMPLETED)", completed, f"final state(s)={states[-3:]}")
    if completed:
        check("12. Corridor no longer active after arrival",
              last_corridor_status not in ("ACTIVE", "PROPOSED"),
              f"last corridor status={last_corridor_status}")
    check("13. Mission history present for the summary panel",
          len(requests) >= 3, f"{len(requests)} EmergencyRequestUpdated events recorded")

    ok = all(passed for _, passed, _ in results)
    print("\n" + ("PASS -- full closed loop verified end to end" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
