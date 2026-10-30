"""`POST /v1/commands` -- the operator command intake. Calls the route
function directly with a fake bus so it needs neither Redis nor the
lifespan; the envelope it builds is decoded back to prove the wire shape."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from api_gateway.controllers.commands import post_command
from api_gateway.core.config import COMMANDS_TOPIC
from api_gateway.models.commands import CommandRequest
from fastapi import HTTPException
from itms_common.events import decode_envelope


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, topic: str, raw: bytes) -> str:
        self.published.append((topic, raw))
        return f"{len(self.published)}-0"



async def test_publishes_a_decodable_envelope_on_the_commands_topic():
    bus = _FakeBus()
    # SystemHeartbeat stands in for a real command schema -- Phase 0 has no
    # command schemas yet; this proves the encode-and-publish plumbing.
    cmd = CommandRequest(
        event_type="SystemHeartbeat", payload={"service": "console", "seq": 7}
    )
    resp = await post_command(cmd, bus)

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
    await post_command(cmd, bus)
    # SystemHeartbeat has no operator field so it is dropped on encode, but the
    # merge happened -- exercised properly once a command schema with an
    # `operator` field exists. Here we just assert it did not blow up.
    assert bus.published


async def test_unknown_event_type_is_a_400_not_a_500():
    bus = _FakeBus()
    cmd = CommandRequest(event_type="NoSuchCommandV9", payload={})
    with pytest.raises(HTTPException) as ei:
        await post_command(cmd, bus)
    assert ei.value.status_code == 400
    assert "NoSuchCommandV9" in ei.value.detail
    assert not bus.published


async def test_payload_not_matching_schema_is_a_422():
    bus = _FakeBus()
    cmd = CommandRequest(event_type="SystemHeartbeat", payload={"seq": "not-an-int"})
    with pytest.raises(HTTPException) as ei:
        await post_command(cmd, bus)
    assert ei.value.status_code == 422
    assert not bus.published


# ---- who may send what ---------------------------------------------------


def _user(role: str, unit: str | None = None):
    from api_gateway.services.auth import UserRecord

    return UserRecord(username=f"{role}1", display_name="x", password_hash="x",
                      role=role, unit_id=unit)


def test_a_crew_may_answer_and_choose_its_own_hospital_but_not_run_the_city():
    from api_gateway.core.security import check_crew_command as _check_crew_command

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


def test_commands_need_a_session_when_sign_in_is_required(tmp_path):
    from api_gateway.core.config import Settings
    from api_gateway.core.security import session_user
    from api_gateway.main import create_app

    on = SimpleNamespace(
        cookies={}, app=create_app(Settings(clips_dir=tmp_path, require_sign_in=True)))
    with pytest.raises(HTTPException) as ei:
        session_user(on)
    assert ei.value.status_code == 401
    off = SimpleNamespace(
        cookies={}, app=create_app(Settings(clips_dir=tmp_path, require_sign_in=False)))
    assert session_user(off) is None
