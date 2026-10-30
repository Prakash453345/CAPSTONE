"""HTTP-level tests for the incident endpoints. `TestClient(app)` used
without a `with` block deliberately never runs the app's `lifespan` (no real
Redis connection attempted, no background consumer task) -- confirmed
against this FastAPI/Starlette version before relying on it here. Each test
supplies its own fake bus via `app.state.bus` and a fresh registry, so tests
don't share incident state or a real Redis instance.
"""

from __future__ import annotations

import pytest
from api_service import main
from api_service.incidents import IncidentRegistry
from fastapi.testclient import TestClient
from itms_common.events import decode_envelope, encode_envelope
from itms_common.incident_events import candidate_payload
from itms_domain.incident import Incident


class _FakeBus:
    def __init__(self):
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, topic: str, raw: bytes) -> str:
        self.published.append((topic, raw))
        return f"id-{len(self.published)}"


@pytest.fixture
def client():
    main.registry = IncidentRegistry()
    main.app.state.bus = _FakeBus()
    return TestClient(main.app)


def _seed_candidate(incident_id: str = "inc-1") -> Incident:
    inc = Incident.raise_candidate(
        incident_id=incident_id,
        link_id="L4",
        intersection_id="J3",
        at_ms=1_725_600_123_456,
        graph_score=6.1,
        fused_probability=0.94,
        threshold_tau=0.80,
        detector_version="graph-ae@abcd1234/conformal@deadbeef",
    )
    raw = encode_envelope(
        event_type="IncidentCandidate", source="sim-service",
        payload=candidate_payload(inc, sim_tick=1), partition_key="J3",
    )
    env = decode_envelope(raw)
    main.registry.apply_event(env["event_type"], env["payload"])
    return inc


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_incidents_empty(client):
    r = client.get("/v1/incidents")
    assert r.status_code == 200
    assert r.json() == []


def test_get_unknown_incident_is_404(client):
    r = client.get("/v1/incidents/does-not-exist")
    assert r.status_code == 404


def test_list_and_get_reflect_a_seeded_candidate(client):
    _seed_candidate()
    r = client.get("/v1/incidents")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["incident_id"] == "inc-1"
    assert body[0]["state"] == "candidate"

    r2 = client.get("/v1/incidents/inc-1")
    assert r2.status_code == 200
    assert r2.json()["incident_id"] == "inc-1"


def test_confirm_without_api_key_is_401(client):
    _seed_candidate()
    r = client.post("/v1/incidents/inc-1/confirm", json={"actor": "op-1"})
    assert r.status_code == 401


def test_confirm_with_wrong_api_key_is_401(client):
    _seed_candidate()
    r = client.post(
        "/v1/incidents/inc-1/confirm",
        json={"actor": "op-1"},
        headers={"X-API-Key": "wrong"},
    )
    assert r.status_code == 401


def test_confirm_with_correct_api_key_succeeds_and_publishes(client):
    _seed_candidate()
    r = client.post(
        "/v1/incidents/inc-1/confirm",
        json={"actor": "op-1", "classification": "stall", "detail": "seen on camera"},
        headers={"X-API-Key": main.API_KEY},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "confirmed"
    assert body["classification"] == "stall"

    bus = main.app.state.bus
    assert len(bus.published) == 1
    topic, raw = bus.published[0]
    assert topic == "incident.detected"
    env = decode_envelope(raw)
    assert env["event_type"] == "IncidentDetected"
    assert env["payload"]["chain_hash"] == body["chain_head"]


def test_confirm_unknown_id_is_404(client):
    r = client.post(
        "/v1/incidents/nope/confirm",
        json={"actor": "op-1"},
        headers={"X-API-Key": main.API_KEY},
    )
    assert r.status_code == 404


def test_confirm_twice_is_409(client):
    _seed_candidate()
    headers = {"X-API-Key": main.API_KEY}
    first = client.post("/v1/incidents/inc-1/confirm", json={"actor": "op-1"}, headers=headers)
    assert first.status_code == 200
    second = client.post("/v1/incidents/inc-1/confirm", json={"actor": "op-1"}, headers=headers)
    assert second.status_code == 409


def test_confirm_unknown_classification_is_422(client):
    _seed_candidate()
    r = client.post(
        "/v1/incidents/inc-1/confirm",
        json={"actor": "op-1", "classification": "not-a-real-classification"},
        headers={"X-API-Key": main.API_KEY},
    )
    assert r.status_code == 422


def test_reject_requires_api_key(client):
    _seed_candidate()
    r = client.post("/v1/incidents/inc-1/reject", json={"actor": "op-1"})
    assert r.status_code == 401


def test_reject_with_correct_api_key_succeeds_and_publishes(client):
    _seed_candidate()
    r = client.post(
        "/v1/incidents/inc-1/reject",
        json={"actor": "op-2", "detail": "false alarm"},
        headers={"X-API-Key": main.API_KEY},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "rejected"

    bus = main.app.state.bus
    assert len(bus.published) == 1
    topic, raw = bus.published[0]
    assert topic == "incident.updated"
    env = decode_envelope(raw)
    assert env["event_type"] == "IncidentUpdated"
    assert env["payload"]["new_state"] == "REJECTED"


def test_read_endpoints_need_a_session_when_sign_in_is_required(monkeypatch):
    from api_service import main
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "REQUIRE_SIGN_IN", True)
    client = TestClient(main.app)
    for path in ("/v1/incidents", "/v1/incidents/x", "/v1/clips", "/v1/clips/x",
                 "/v1/clips/x/video", "/v1/clips/x/snapshot"):
        assert client.get(path).status_code == 401, path
    assert client.post("/v1/clips", files={"file": ("a.mp4", b"x")},
                       data={"edge_id": "e"}).status_code == 401


def test_crew_accounts_cannot_read_clips_or_incidents(monkeypatch):
    from types import SimpleNamespace

    import pytest
    from api_service import main
    from fastapi import HTTPException

    monkeypatch.setattr(main, "REQUIRE_SIGN_IN", True)
    monkeypatch.setattr(main, "_session_user", lambda request: SimpleNamespace(role="responder"))
    with pytest.raises(HTTPException) as ei:
        main._operator_only(SimpleNamespace(cookies={}))
    assert ei.value.status_code == 403
    monkeypatch.setattr(main, "_session_user", lambda request: SimpleNamespace(role="operator"))
    main._operator_only(SimpleNamespace(cookies={}))


def test_a_signed_in_operator_can_review_without_the_api_key(monkeypatch):
    from types import SimpleNamespace

    import pytest
    from api_service import main
    from fastapi import HTTPException

    monkeypatch.setattr(main, "REQUIRE_SIGN_IN", True)
    req = SimpleNamespace(cookies={})
    monkeypatch.setattr(main.auth_mod, "get_user_store", lambda: None)
    monkeypatch.setattr(main.auth_mod, "current_user", lambda r, s: SimpleNamespace(role="operator"))  # noqa: E501
    main.require_reviewer(req, "")                                      # operator session
    monkeypatch.setattr(main.auth_mod, "current_user", lambda r, s: SimpleNamespace(role="responder"))  # noqa: E501
    with pytest.raises(HTTPException) as ei:
        main.require_reviewer(req, "")
    assert ei.value.status_code == 403
    main.require_reviewer(req, main.API_KEY)                            # a script with the key
    monkeypatch.setattr(main, "REQUIRE_SIGN_IN", False)
    with pytest.raises(HTTPException) as ei:
        main.require_reviewer(req, "wrong")
    assert ei.value.status_code == 401
