"""Uploaded road videos: upload limits, the analysis read model, the review
gate, and the command a confirmation publishes. A fake bus and a temporary
clips directory stand in for Redis and the shared volume."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from api_gateway.core.config import COMMANDS_TOPIC, Settings
from api_gateway.main import create_app
from api_gateway.services.clip_registry import ClipRegistry
from fastapi.testclient import TestClient
from itms_common.events import decode_envelope, encode_envelope


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def publish(self, topic: str, raw: bytes) -> str:
        self.published.append((topic, decode_envelope(raw)))
        return f"{len(self.published)}-0"


API_KEY = "test-key"


@pytest.fixture
def make_api(tmp_path):
    """An isolated app over a temporary clips directory; no lifespan, so no Redis."""
    def make(**settings):
        app = create_app(Settings(api_key=API_KEY, clips_dir=tmp_path.resolve(), **settings))
        bus = FakeBus()
        app.state.bus = bus
        return TestClient(app), bus, app.state.clips
    return make


@pytest.fixture
def api(make_api):
    return make_api()


def upload(client, name="crash.mp4", data=b"\x00" * 2048, edge="E1"):
    return client.post("/v1/clips", files={"file": (name, data, "video/mp4")},
                       data={"edge_id": edge, "road_name": "MG Road", "latitude": "16.5",
                             "longitude": "80.6"})


def analysed(clip_id: str, registry, tmp_path, *, anomaly="accident", severity="high",
             snapshot=True) -> dict:
    snap = None
    if snapshot:
        snap = tmp_path / clip_id / "snapshot.jpg"
        snap.write_bytes(b"\xff\xd8jpeg")
    payload = {
        "clip_id": clip_id, "status": "DONE", "progress": 1.0,
        "anomaly_type": anomaly, "severity": severity if anomaly else None,
        "confidence": 0.91 if anomaly else None, "flagged_at_s": 12.5 if anomaly else None,
        "reasons": (["accident model: 3 of 5 frames at or above 0.50 (peak 0.91)"]
                    if anomaly else []),
        "findings_json": json.dumps(
            [{"anomaly_type": anomaly, "start_s": 12.5}] if anomaly else []),
        "timeline_json": json.dumps({"t": [0, 1], "accident": [0.1, 0.9]}),
        "detectors": ["accident"], "snapshot_path": str(snap) if snap else None,
        "duration_s": 30.0, "error": "",
        "analysed_at": dt.datetime(2026, 10, 11, tzinfo=dt.UTC),
    }
    # through the wire contract, as the consumer would see it
    decoded = decode_envelope(encode_envelope("ClipAnalysed", source="t", payload=payload))
    registry.apply_analysed(decoded["payload"])
    return decoded["payload"]


def key():
    return {"X-API-Key": API_KEY}


# ---------------------------------------------------------------- upload


def test_an_upload_is_stored_and_queued_for_the_vision_worker(api, tmp_path):
    client, bus, _ = api
    r = upload(client)
    assert r.status_code == 201
    clip = r.json()
    assert clip["status"] == "QUEUED" and clip["review"] is None
    assert clip["video_url"] == f"/v1/clips/{clip['clip_id']}/video"
    assert "video_path" not in clip                      # no server paths in the API
    stored = tmp_path / clip["clip_id"] / "source.mp4"
    assert stored.read_bytes() == b"\x00" * 2048
    topic, env = bus.published[0]
    assert topic == "vision.clip-submitted" and env["event_type"] == "ClipSubmitted"
    assert env["payload"]["video_path"] == str(stored)
    assert env["payload"]["edge_id"] == "E1" and env["payload"]["latitude"] == 16.5


def test_an_upload_that_is_not_a_video_or_is_empty_is_refused_and_leaves_nothing(api, tmp_path):
    client, bus, _ = api
    assert upload(client, name="notes.txt").status_code == 415
    assert upload(client, data=b"").status_code == 422
    assert list(tmp_path.iterdir()) == [] and bus.published == []


def test_an_upload_over_the_size_limit_is_refused(make_api, tmp_path):
    client, _, _ = make_api(clip_max_bytes=1000)
    assert upload(client).status_code == 413
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- analysis read model


def test_progress_then_a_finding_makes_a_review_item(api, tmp_path):
    client, _, registry = api
    clip_id = upload(client).json()["clip_id"]
    registry.apply_analysed({"clip_id": clip_id, "status": "ANALYSING", "progress": 0.4})
    assert client.get(f"/v1/clips/{clip_id}").json()["progress"] == pytest.approx(0.4)

    analysed(clip_id, registry, tmp_path)
    clip = client.get(f"/v1/clips/{clip_id}").json()
    assert clip["status"] == "DONE" and clip["review"] == "PENDING"
    assert clip["anomaly_type"] == "accident" and clip["severity"] == "high"
    assert clip["flagged_at_s"] == 12.5
    assert clip["findings"][0]["anomaly_type"] == "accident"
    assert clip["timeline"]["accident"] == [0.1, 0.9]
    assert clip["snapshot_url"] == f"/v1/clips/{clip_id}/snapshot"
    assert client.get(clip["snapshot_url"]).content == b"\xff\xd8jpeg"

    # a progress event arriving after the result does not undo it
    registry.apply_analysed({"clip_id": clip_id, "status": "ANALYSING", "progress": 0.9})
    assert client.get(f"/v1/clips/{clip_id}").json()["status"] == "DONE"


def test_a_clip_with_nothing_found_has_nothing_to_review(api, tmp_path):
    client, bus, registry = api
    clip_id = upload(client).json()["clip_id"]
    analysed(clip_id, registry, tmp_path, anomaly=None, snapshot=False)
    clip = client.get(f"/v1/clips/{clip_id}").json()
    assert clip["review"] is None and clip["snapshot_url"] is None
    r = client.post(f"/v1/clips/{clip_id}/confirm", json={"actor": "op"}, headers=key())
    assert r.status_code == 409


def test_the_video_can_be_seeked(api):
    client, _, _ = api
    clip_id = upload(client, data=bytes(range(256)) * 8).json()["clip_id"]
    r = client.get(f"/v1/clips/{clip_id}/video", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == bytes(range(10, 20))
    assert r.headers["content-type"] == "video/mp4"


def test_a_stored_path_outside_the_clips_directory_is_never_served(api, tmp_path_factory):
    client, _, registry = api
    clip_id = upload(client).json()["clip_id"]
    outside = tmp_path_factory.mktemp("elsewhere") / "secret.jpg"
    outside.write_bytes(b"secret")
    registry.get(clip_id).result = {"snapshot_path": str(outside)}
    assert client.get(f"/v1/clips/{clip_id}/snapshot").status_code == 404


# ---------------------------------------------------------------- review


def test_confirming_needs_the_api_key(api, tmp_path):
    client, _, registry = api
    clip_id = upload(client).json()["clip_id"]
    analysed(clip_id, registry, tmp_path)
    assert client.post(f"/v1/clips/{clip_id}/confirm", json={"actor": "op"}).status_code == 401


def test_confirming_publishes_the_same_command_as_the_create_anomaly_panel(api, tmp_path):
    client, bus, registry = api
    clip_id = upload(client).json()["clip_id"]
    analysed(clip_id, registry, tmp_path)
    bus.published.clear()

    r = client.post(f"/v1/clips/{clip_id}/confirm", headers=key(),
                    json={"actor": "operator:asha", "severity": "blocked"})
    assert r.status_code == 200
    clip = r.json()
    assert clip["review"] == "CONFIRMED" and clip["reviewed_by"] == "operator:asha"
    assert clip["confirmed_type"] == "accident" and clip["confirmed_severity"] == "blocked"

    topic, env = bus.published[0]
    assert topic == COMMANDS_TOPIC and env["event_type"] == "AnomalyCreateRequested"
    p = env["payload"]
    assert p["anomaly_id"] == clip["anomaly_id"] and p["edge_id"] == "E1"
    assert p["anomaly_type"] == "ACCIDENT" and p["severity"] == "BLOCKED"
    assert p["operator"] == "operator:asha"
    assert p["detail"].startswith("confirmed from video clip crash.mp4: accident model")

    again = client.post(f"/v1/clips/{clip_id}/confirm", headers=key(), json={"actor": "op"})
    assert again.status_code == 409


def test_a_fire_finding_confirms_as_a_fire_anomaly(api, tmp_path):
    client, bus, registry = api
    clip_id = upload(client).json()["clip_id"]
    analysed(clip_id, registry, tmp_path, anomaly="fire")
    bus.published.clear()
    client.post(f"/v1/clips/{clip_id}/confirm", headers=key(), json={"actor": "op"})
    assert bus.published[0][1]["payload"]["anomaly_type"] == "FIRE"


def test_the_reviewer_can_correct_the_type_but_not_to_nonsense(api, tmp_path):
    client, bus, registry = api
    clip_id = upload(client).json()["clip_id"]
    analysed(clip_id, registry, tmp_path)
    bad = client.post(f"/v1/clips/{clip_id}/confirm", headers=key(),
                      json={"actor": "op", "anomaly_type": "alien_landing"})
    assert bad.status_code == 422
    assert client.get(f"/v1/clips/{clip_id}").json()["review"] == "PENDING"
    ok = client.post(f"/v1/clips/{clip_id}/confirm", headers=key(),
                     json={"actor": "op", "anomaly_type": "vehicle_breakdown"})
    assert ok.json()["confirmed_type"] == "vehicle_breakdown"
    assert bus.published[-1][1]["payload"]["anomaly_type"] == "VEHICLE_BREAKDOWN"


def test_rejecting_dismisses_without_dispatching(api, tmp_path):
    client, bus, registry = api
    clip_id = upload(client).json()["clip_id"]
    analysed(clip_id, registry, tmp_path)
    bus.published.clear()
    r = client.post(f"/v1/clips/{clip_id}/reject", headers=key(),
                    json={"actor": "op", "note": "shadow, not a crash"})
    assert r.json()["review"] == "REJECTED" and r.json()["review_note"] == "shadow, not a crash"
    assert bus.published == []
    assert client.post(f"/v1/clips/{clip_id}/confirm", headers=key(),
                       json={"actor": "op"}).status_code == 409


def test_clips_survive_an_api_restart(api, tmp_path):
    client, _, registry = api
    clip_id = upload(client).json()["clip_id"]
    payload = analysed(clip_id, registry, tmp_path)
    client.post(f"/v1/clips/{clip_id}/reject", headers=key(), json={"actor": "op"})

    reloaded = ClipRegistry(tmp_path)
    clip = reloaded.get(clip_id)
    assert clip is not None and clip.review == "REJECTED"
    assert clip.result["anomaly_type"] == payload["anomaly_type"]


def test_a_result_the_worker_wrote_while_the_api_was_down_is_picked_up(api, tmp_path):
    client, _, _ = api
    clip_id = upload(client).json()["clip_id"]
    (tmp_path / clip_id / "result.json").write_text(json.dumps({
        "clip_id": clip_id, "status": "DONE", "progress": 1.0, "anomaly_type": "fire",
        "severity": "high", "findings_json": "[]", "timeline_json": "{}",
        "analysed_at": 1_760_000_000_000}))
    clip = ClipRegistry(tmp_path).get(clip_id)
    assert clip is not None and clip.status == "DONE" and clip.review == "PENDING"
