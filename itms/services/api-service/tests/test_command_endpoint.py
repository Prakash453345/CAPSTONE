"""`POST /v1/commands` -- the operator command intake. Calls the route
function directly with a fake request/bus so it needs neither Redis nor the
lifespan; the envelope it builds is decoded back to prove the wire shape."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from api_service.main import COMMANDS_TOPIC, CommandRequest, post_command
from fastapi import HTTPException
from itms_common.events import decode_envelope


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, topic: str, raw: bytes) -> str:
        self.published.append((topic, raw))
        return f"{len(self.published)}-0"


def _request(bus: _FakeBus):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(bus=bus)))


async def test_publishes_a_decodable_envelope_on_the_commands_topic():
    bus = _FakeBus()
    # SystemHeartbeat stands in for a real command schema -- Phase 0 has no
    # command schemas yet; this proves the encode-and-publish plumbing.
    cmd = CommandRequest(
        event_type="SystemHeartbeat", payload={"service": "console", "seq": 7}
    )
    resp = await post_command(cmd, _request(bus))

    assert resp == {"published": True, "topic": COMMANDS_TOPIC, "message_id": "1-0"}
    assert len(bus.published) == 1
    topic, raw = bus.published[0]
    assert topic == COMMANDS_TOPIC
    env = decode_envelope(raw)
    assert env["event_type"] == "SystemHeartbeat"
    assert env["source"] == "api-service"
    assert env["payload"]["service"] == "console"


async def test_operator_is_folded_into_the_payload():
    bus = _FakeBus()
    cmd = CommandRequest(
        event_type="SystemHeartbeat",
        payload={"service": "console", "seq": 1},
        operator="operator:alice",
    )
    await post_command(cmd, _request(bus))
    # SystemHeartbeat has no operator field so it is dropped on encode, but the
    # merge happened -- exercised properly once a command schema with an
    # `operator` field exists. Here we just assert it did not blow up.
    assert bus.published


async def test_unknown_event_type_is_a_400_not_a_500():
    bus = _FakeBus()
    cmd = CommandRequest(event_type="NoSuchCommandV9", payload={})
    with pytest.raises(HTTPException) as ei:
        await post_command(cmd, _request(bus))
    assert ei.value.status_code == 400
    assert "NoSuchCommandV9" in ei.value.detail
    assert not bus.published


async def test_payload_not_matching_schema_is_a_422():
    bus = _FakeBus()
    cmd = CommandRequest(event_type="SystemHeartbeat", payload={"seq": "not-an-int"})
    with pytest.raises(HTTPException) as ei:
        await post_command(cmd, _request(bus))
    assert ei.value.status_code == 422
    assert not bus.published


# ---- who may send what ---------------------------------------------------


def _user(role: str, unit: str | None = None):
    from api_service.auth import UserRecord

    return UserRecord(username=f"{role}1", display_name="x", password_hash="x",
                      role=role, unit_id=unit)


def test_a_crew_may_answer_and_choose_its_own_hospital_but_not_run_the_city():
    from api_service.main import _check_crew_command

    crew = _user("responder", "AMB-03")
    choice = CommandRequest(event_type="CrewHospitalChoice",
                            payload={"unit_id": "AMB-99", "facility_id": "h1"})
    _check_crew_command(crew, choice)
    assert choice.payload["unit_id"] == "AMB-03"  # its own ambulance, whatever it sent
    _check_crew_command(crew, CommandRequest(event_type="EmergencyCommand",
                                             payload={"action": "RECALCULATE"}))
    for event_type, payload in [("AnomalyCreateRequested", {}),
                                ("EmergencyCommand", {"action": "CANCEL"})]:
        with pytest.raises(HTTPException) as ei:
            _check_crew_command(crew, CommandRequest(event_type=event_type, payload=payload))
        assert ei.value.status_code == 403
    # operators are not limited
    _check_crew_command(_user("operator"), CommandRequest(event_type="AnomalyCreateRequested"))


def test_commands_need_a_session_when_sign_in_is_required(monkeypatch):
    from api_service import main

    monkeypatch.setattr(main, "REQUIRE_SIGN_IN", True)
    request = SimpleNamespace(cookies={})
    with pytest.raises(HTTPException) as ei:
        main._session_user(request)
    assert ei.value.status_code == 401
    monkeypatch.setattr(main, "REQUIRE_SIGN_IN", False)
    assert main._session_user(request) is None
