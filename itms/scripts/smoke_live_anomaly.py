"""End-to-end smoke for the operator-anomaly path (Phase 3).

Needs Redis + SUMO. Not a pytest target (the unit coverage is
`test_anomaly_control.py` / `test_live_service.py` / `test_command_endpoint.py`).

Flow exercised:
    pre-create the `sim-service-live` consumer group
    -> publish an AnomalyCreateRequested on `commands.operator`
    -> run_live(max_steps=N): drains it, applies the lane-speed reduction in
       SUMO, emits AnomalyUpdated on `anomaly.updated`
    -> read `anomaly.updated` back and assert an ACTIVE anomaly for our edge.

Usage:  python scripts/smoke_live_anomaly.py [demand]   (light | medium | heavy)
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
sys.path.insert(0, str(_ROOT / "services" / "sim-service"))

from sim_service.live.corridor import link_to_lane_map  # noqa: E402
from sim_service.live.service import CONSUMER_GROUP, run_live  # noqa: E402

REDIS_URL = "redis://localhost:6379/0"
ANOMALY_TOPIC = "anomaly.updated"
COMMANDS_TOPIC = "commands.operator"
MAX_STEPS = 90


def _pick_edge() -> str:
    """A real controlled-approach edge from the corridor -- derived from the
    first link lane so the anomaly lands somewhere with traffic."""
    link_lanes = link_to_lane_map()
    for links in link_lanes.values():
        for lane in links.values():
            return lane.rsplit("_", 1)[0]
    raise SystemExit("no controlled lanes found in the corridor")


def main() -> None:
    demand = sys.argv[1] if len(sys.argv) > 1 else "light"
    edge_id = _pick_edge()
    anomaly_id = str(uuid.uuid4())
    r = redis_sync.from_url(REDIS_URL)

    before = r.xlen(ANOMALY_TOPIC) if r.exists(ANOMALY_TOPIC) else 0

    # establish the consumer group *before* publishing, so run_live's consumer
    # sees the command as pending on its first tick
    RedisStreamsSyncConsumer([COMMANDS_TOPIC], group=CONSUMER_GROUP, consumer="smoke",
                             url=REDIS_URL).close()

    bus = RedisStreamsSyncBus(REDIS_URL)
    bus.publish(
        COMMANDS_TOPIC,
        encode_envelope(
            event_type="AnomalyCreateRequested",
            source="smoke",
            payload={
                "anomaly_id": anomaly_id,
                "edge_id": edge_id,
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
    bus.close()
    print(f"published AnomalyCreateRequested {anomaly_id} on edge {edge_id}")

    summary = run_live(
        redis_url=REDIS_URL, demand=demand, realtime_factor=1e6, max_steps=MAX_STEPS
    )
    print(f"run_live: {summary}")

    entries = r.xrange(ANOMALY_TOPIC, min="-", max="+")[before:]
    ours = [
        decode_envelope(fields[b"raw"])["payload"]
        for _, fields in entries
        if decode_envelope(fields[b"raw"])["payload"]["anomaly_id"] == anomaly_id
    ]
    active = [p for p in ours if p["status"] == "ACTIVE"]

    ok = (
        summary["commands_drained"] >= 1
        and active
        and active[0]["edge_id"] == edge_id
        and active[0]["severity"] == "high"
        and active[0]["estimated_impact"] > 0
    )
    print(f"\ncommands_drained : {summary['commands_drained']}")
    print(f"AnomalyUpdated for our id : {len(ours)}  (ACTIVE: {len(active)})")
    if active:
        print(f"  {active[0]}")
    print(f"\n{'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
