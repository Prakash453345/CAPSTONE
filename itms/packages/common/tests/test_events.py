"""Pure roundtrip test — no Redis, no network. Proves the envelope/payload
Avro encode-decode path is correct in isolation, before ever involving the bus."""

from itms_common.events import decode_envelope, encode_envelope


def test_system_heartbeat_roundtrip():
    raw = encode_envelope(
        event_type="SystemHeartbeat",
        source="pytest",
        payload={"service": "pytest", "seq": 42, "message": "hi"},
        partition_key="test-key",
    )
    assert isinstance(raw, bytes)

    envelope = decode_envelope(raw)

    assert envelope["event_type"] == "SystemHeartbeat"
    assert envelope["source"] == "pytest"
    assert envelope["partition_key"] == "test-key"
    assert envelope["payload"] == {"service": "pytest", "seq": 42, "message": "hi"}


def test_default_message_field():
    raw = encode_envelope(
        event_type="SystemHeartbeat",
        source="pytest",
        payload={"service": "pytest", "seq": 1},
    )
    envelope = decode_envelope(raw)
    assert envelope["payload"]["message"] == "hello"
