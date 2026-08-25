"""Integration test -- needs a real Redis and shells out to a real SUMO
process against the Vijayawada corridor network. Skipped unless
RUN_INTEGRATION_TESTS=1, the same gate
`packages/common/tests/test_bus_integration.py` already uses, so `make
test` stays runnable without live infra.

Proves `control/runner.py`'s `bus` parameter actually publishes real,
decodable `SignalChanged` events onto `signal.changed` during a live
scenario -- the loose end PROGRESS.md's M2 section flagged ("not yet
wired onto the bus") and this session closes. `test_signal_events.py`
already proves the payload shape round-trips through the schema in
isolation; this proves the wiring that gets it there actually fires
during a real run, which a pure unit test can't.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import redis as redis_sync
from itms_common.bus import RedisStreamsSyncBus
from itms_common.events import decode_envelope
from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies import fixed_time

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 with a Redis reachable at REDIS_URL to run this",
)

_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_ROOT / "scenarios" / "networks" / "vijayawada"))
from extract_tier0_config import load_configs  # noqa: E402

_NET_PATH = _ROOT / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
_SUMOCFG_PATH = _ROOT / "scenarios" / "demand" / "vijayawada" / "vijayawada_corridor.sumocfg"
_TOPIC = "signal.changed"


def test_run_controlled_scenario_publishes_real_signal_changed_events():
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    configs = load_configs(_NET_PATH)

    raw_redis = redis_sync.from_url(url)
    before_len = raw_redis.xlen(_TOPIC) if raw_redis.exists(_TOPIC) else 0

    bus = RedisStreamsSyncBus(url)
    try:
        result = run_controlled_scenario(
            str(_SUMOCFG_PATH),
            configs,
            strategy=fixed_time.propose,
            seed=1,
            bus=bus,
            max_steps=5,
        )
    finally:
        bus.close()

    assert result["interlock_violations"] == 0

    entries = raw_redis.xrange(_TOPIC, min="-", max="+")
    new_entries = entries[before_len:]
    assert new_entries, "run_controlled_scenario's bus parameter published nothing"

    _, fields = new_entries[0]
    envelope = decode_envelope(fields[b"raw"])
    assert envelope["event_type"] == "SignalChanged"
    assert envelope["source"] == "sim-service"
    assert envelope["payload"]["intersection_id"] in configs
    assert envelope["payload"]["source"] == "fixed_time"
