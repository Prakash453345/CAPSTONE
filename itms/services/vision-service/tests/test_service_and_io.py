"""Events round-trip through the Avro contracts; the service core publishes
the right things; placement, calibration, privacy, MOT scoring and the
closed-loop wrapper behave."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pytest
from itms_common.events import decode_envelope, encode_envelope
from itms_domain import JunctionContext
from itms_geo.camera import homography_camera_from_pinhole
from vision_service.cameras import CameraRig, CameraSpec, load_registry, save_registry
from vision_service.classes import VClass
from vision_service.eval.metrics import ClearMot
from vision_service.eval.mot import evaluate, write_mot
from vision_service.events import anomaly_payload, camera_status_payload, link_state_payload
from vision_service.health import CameraStatus
from vision_service.incidents.rules import AnomalyCandidate
from vision_service.placement import plan_approach_camera
from vision_service.privacy import EvidenceBuffer, EvidenceStore, redact, redaction_regions
from vision_service.records import Detection
from vision_service.service import VisionService
from vision_service.sim.closed_loop import VisionSensor
from vision_service.state.estimator import LinkEstimate

from tests.test_simcam import vehicles_on


def _estimate(link="L0") -> LinkEstimate:
    return LinkEstimate("J", link, 2.3, 0.6, 0.12, 1.0, 0.91, 1.0, 1.0, 0.97, 1.0, 0.5, False,
                        0.0, ("camJ",))


def _roundtrip(event_type: str, payload: dict) -> dict:
    return decode_envelope(encode_envelope(event_type, "pytest", payload))["payload"]


def test_link_state_contract_roundtrip() -> None:
    p = link_state_payload("J", {("J", "L0"): _estimate()}, {("J", "L0"): 0.7}, sim_time_s=12.0)
    out = _roundtrip("LinkStateEstimated", p)
    assert out["links"][0]["queue_pcu"] == pytest.approx(2.3)
    assert out["links"][0]["vision_score"] == pytest.approx(0.7)
    assert out["links"][0]["cameras"] == ["camJ"]


def test_camera_status_contract_roundtrip() -> None:
    p = camera_status_payload("camJ", (CameraStatus.DEGRADED, 0.5, ["calibration drift"]),
                              lonlat=(80.6, 16.5), heading_deg=270.0)
    out = _roundtrip("CameraStatus", p)
    assert out["status"] == "DEGRADED" and out["reasons"] == ["calibration drift"]


def test_vision_anomaly_uses_the_existing_contract() -> None:
    cand = AnomalyCandidate("a1", "midblock_stop", "vehicle_breakdown", "medium", "in_0", "in",
                            130.0, (("J", "L0"),), 0.8, 10.0, 13.0, {"stopped_s": 31.0,
                                                                      "truth_id": "veh9"})
    out = _roundtrip("AnomalyUpdated", anomaly_payload(cand, n_lanes_on_edge=2))
    assert out["source"] == "VISION" and out["estimated_impact"] == pytest.approx(0.5)
    assert "truth_id" not in json.loads(out["detail"])  # simulation identity never leaves


@dataclass
class _Bus:
    events: list = field(default_factory=list)

    def __call__(self, topic, event_type, payload, key):
        encode_envelope(event_type, "pytest", payload)  # must satisfy the schema
        self.events.append((topic, event_type, payload))


def test_service_core_publishes_link_state_and_camera_status(network, rig, links) -> None:
    bus = _Bus()
    approach, receiving = links
    svc = VisionService(rig, approach, receiving, bus, preset="ideal", fps=5.0)
    for k in range(6):
        snap = vehicles_on(network, "in_0", [("a", VClass.CAR, 120.0 + 8 * k, 8.0)], t=float(k))
        svc.system.step_world(svc._prev_snap, snap)
        svc._prev_snap = snap
        svc.tick(float(k))
    kinds = {e[1] for e in bus.events}
    assert {"LinkStateEstimated", "CameraStatus"} <= kinds
    ls = [e for e in bus.events if e[1] == "LinkStateEstimated"][-1][2]
    assert {row["link_id"] for row in ls["links"]} == {"L0", "L1"}


def test_a_resolved_incident_keeps_the_time_it_began(network, rig, links, monkeypatch) -> None:
    bus = _Bus()
    approach, receiving = links
    svc = VisionService(rig, approach, receiving, bus, preset="ideal")
    eng = svc.system.incidents
    cand = AnomalyCandidate("a1", "midblock_stop", "vehicle_breakdown", "medium", "in_0", "in",
                            130.0, (("J", "L0"),), 0.8, 10.0, 13.0, {})
    real_update = eng.update

    def update(t, tracks, est):
        out = real_update(t, tracks, est)
        if t == 13.0:
            eng.new_candidates = [cand]
        if t == 73.0:
            cand.status = "RESOLVED"
            eng.resolved = [cand]
        return out

    monkeypatch.setattr(eng, "update", update)
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr("vision_service.service.time.time", lambda: clock["now"])
    for t in (13.0, 73.0):
        clock["now"] = 1_000_000.0 + t
        svc.tick(t, sim_time_s=t)
    ups = [e[2] for e in bus.events if e[1] == "AnomalyUpdated"]
    assert [u["status"] for u in ups] == ["ACTIVE", "RESOLVED"]
    assert ups[0]["start_time_ms"] == ups[1]["start_time_ms"] == (1_000_000 + 10) * 1000
    assert ups[1]["sim_tick"] == 73


def test_signal_changed_drives_the_rules_phase_state(network, rig, links) -> None:
    network.green_phases["J"] = ["GG", "rr"]
    bus = _Bus()
    approach, receiving = links
    svc = VisionService(rig, approach, receiving, bus, preset="ideal")
    svc.on_signal_changed(5.0, {"intersection_id": "J", "phase_id": "P0"})
    assert svc.signal.link_state("J", "L0") == "G"
    assert svc.signal.green_since("J", "L1") == 5.0


def test_planner_puts_the_stop_line_in_view(network) -> None:
    res = plan_approach_camera(network, "J", "in")
    assert all(v > 60 for v in res.covered_from_stopline_m.values())


def test_registry_roundtrip(tmp_path, network, camera) -> None:
    specs = [CameraSpec("a", camera, tls_id="J"),
             CameraSpec("b", homography_camera_from_pinhole(camera), source="rtsp://x")]
    save_registry(tmp_path / "r.json", specs, network="net.xml")
    got, raw = load_registry(tmp_path / "r.json")
    assert [s.camera_id for s in got] == ["a", "b"] and got[1].source == "rtsp://x"
    rig = CameraRig.build(network, got)
    cov = rig.coverage("in_0")
    assert cov is not None and cov.covered_from_end_m > 60


def test_calibration_from_points_recovers_the_camera(network, camera) -> None:
    from vision_service.calibrate import calibrate

    lane = network.lanes["in_0"]
    ground = np.vstack([lane.point_at(s, lat) for s, lat in
                        [(150, -1.5), (150, 5.0), (190, -1.5), (190, 5.0), (170, 1.0),
                         (120, 0.0)]])
    uv, _ = camera.ground_to_image(ground)
    uv[5] += [40.0, -25.0]  # one mis-clicked point
    pts = {"camera_id": "c", "image_size": [1920, 1080], "nadir_xy": [216.0, -3.2],
           "points": [{"image": list(map(float, u)), "xy": list(map(float, g))}
                      for u, g in zip(uv, ground, strict=True)]}
    cam, rep = calibrate(pts, network)
    assert rep["outliers"] == [5] and rep["rms_px"] < 1e-3
    probe = lane.point_at(np.array([140.0, 180.0]))
    np.testing.assert_allclose(cam.ground_to_image(probe)[0], camera.ground_to_image(probe)[0],
                               atol=1e-2)


def test_redaction_covers_people_riders_and_plates() -> None:
    frame = (np.arange(200 * 300 * 3) % 251).astype(np.uint8).reshape(200, 300, 3)
    dets = [Detection((10, 10, 50, 110), 0.9, VClass.PERSON),
            Detection((100, 20, 140, 120), 0.9, VClass.MOTORCYCLE),
            Detection((180, 60, 290, 150), 0.9, VClass.CAR)]
    out = redact(frame, dets)
    assert not np.shares_memory(out, frame)
    for x1, y1, x2, y2 in redaction_regions(dets):
        region = out[y1:y2, x1:x2].astype(int)
        assert region.std() < frame[y1:y2, x1:x2].astype(int).std()
    assert (out[0:5, 0:5] == frame[0:5, 0:5]).all()  # outside every box: untouched


def test_evidence_is_redacted_and_expires(tmp_path) -> None:
    buf = EvidenceBuffer(seconds=3.0, fps=2.0, scale=0.5)
    frame = np.full((100, 100, 3), 200, dtype=np.uint8)
    for k in range(20):
        buf.push(k * 0.25, frame, [Detection((10, 10, 40, 60), 0.9, VClass.PERSON)])
    assert len(buf) <= 7  # 3 s at 2 fps, never more
    store = EvidenceStore(root=tmp_path, retention_days=1)
    where = store.save("an1", "camJ", buf.redacted_clip())
    meta = json.loads((tmp_path / "an1" / "camJ" / "evidence.json").read_text())
    assert meta["redacted"] and where
    assert store.purge_expired(now=meta["delete_after_unix"] + 1) == 1
    assert not (tmp_path / "an1").exists()  # nothing left behind, not even the folder name


def test_mot_file_evaluation(tmp_path) -> None:
    gt = [(f, 1, np.array([10 + f, 10, 50 + f, 40]), 1.0) for f in range(1, 11)]
    pred = [(f, 7, np.array([11 + f, 10, 51 + f, 40]), 0.9) for f in range(1, 11)]
    write_mot(tmp_path / "gt.txt", gt)
    write_mot(tmp_path / "pred.txt", pred)
    res = evaluate(tmp_path / "gt.txt", tmp_path / "pred.txt")
    assert res["mota"] == pytest.approx(1.0) and res["idf1"] == pytest.approx(1.0)


def test_identity_switch_is_counted() -> None:
    m = ClearMot()
    box = np.array([[0, 0, 10, 10]])
    m.update([1], box, ["a"], box)
    m.update([2], box, ["a"], box)
    assert m.idsw == 1 and m.idf1 == pytest.approx(0.5)


def test_a_near_tie_does_not_count_as_an_identity_switch() -> None:
    # two vehicles side by side, each tracked faithfully; in frame 2 the
    # IoUs make the cross assignment marginally "better". The tracker did
    # nothing wrong, and CLEAR-MOT keeps the existing pairs.
    m = ClearMot()
    truth = np.array([[0, 0, 10, 10], [2, 0, 12, 10]], dtype=float)
    m.update([1, 2], truth, ["a", "b"], truth)
    pred = np.array([[1.5, 0, 11.5, 10], [0.5, 0, 10.5, 10]], dtype=float)  # jitter crosses them
    m.update([1, 2], pred, ["a", "b"], truth)
    assert m.idsw == 0 and m.tp == 4


class _FakeLoop:
    def __init__(self, qs, blocked=None):
        self.qs = qs
        self.blocked = blocked or {}

    def stopbar(self, tls):
        return {}

    def ensure(self, t):
        class S:
            pass

        s = S()
        s.estimator = type("E", (), {"queue_sample": lambda _self, tls: self.qs,
                                     "blocked": self.blocked})()
        return s


def test_closed_loop_wrapper_swaps_exactly_the_queue_fields() -> None:
    qs = {"queue_pcu": {"L0": 5.0}, "approaching_pcu": {"L0": 1.0},
          "receiving_occupancy": {"L0": 0.3}, "receiving_queue_pcu": {"L0": 2.0},
          "confidence": {"L0": 0.6}}
    seen = {}

    class Inner:
        stats: dict = {}

        def set_sim_time(self, t):
            pass

        def __call__(self, cfg, ctx):
            seen["ctx"] = ctx
            return "plan"

    ctx = JunctionContext(intersection_id="J", current_phase_id="P0",
                          current_phase_elapsed_s=3.0, has_demand={"L0": True},
                          wait_times_s={"L0": 9.0}, queue_pcu={"L0": 1.0},
                          receiving_occupancy={"L0": 0.0}, receiving_queue_pcu={"L0": 0.0},
                          approaching_pcu={"L0": 0.0})
    for mode, conf in (("honest", {"L0": 0.6}), ("trust", {})):
        w = VisionSensor(Inner(), _FakeLoop(qs), "J", mode)  # type: ignore[arg-type]
        assert w(None, ctx) == "plan"
        got = seen["ctx"]
        assert got.queue_pcu == {"L0": 5.0} and got.receiving_occupancy == {"L0": 0.3}
        assert dict(got.confidence) == conf
        assert got.wait_times_s == {"L0": 9.0} and got.has_demand == {"L0": True}
        assert got.blocked_by == {}


def test_closed_loop_wrapper_takes_blocked_lanes_from_the_cameras_only() -> None:
    """What the simulator knows about a blocked lane never reaches a
    camera-fed controller; what the overview camera saw does."""
    qs: dict[str, dict] = {"queue_pcu": {}, "approaching_pcu": {}, "receiving_occupancy": {},
          "receiving_queue_pcu": {}, "confidence": {}}
    seen = {}

    class Inner:
        stats: dict = {}

        def set_sim_time(self, t):
            pass

        def __call__(self, cfg, ctx):
            seen["ctx"] = ctx

    ctx = JunctionContext(intersection_id="J", current_phase_id="P0",
                          current_phase_elapsed_s=3.0, blocked_by={"L0": "L2"})
    VisionSensor(Inner(), _FakeLoop(qs), "J", "honest")(None, ctx)  # type: ignore[arg-type]
    assert seen["ctx"].blocked_by == {}
    cams = _FakeLoop(qs, {"J": {"L4": "?"}, "K": {"L0": "?"}})
    VisionSensor(Inner(), cams, "J", "honest")(None, ctx)  # type: ignore[arg-type]
    assert seen["ctx"].blocked_by == {"L4": "?"}


def test_evidence_redacts_tracked_people_the_detector_missed() -> None:
    """A person the detector lost for a frame is still where the tracker
    predicts; evidence redaction uses both."""
    from vision_service.records import ImageTrack
    from vision_service.service import tracked_boxes

    coasting = ImageTrack(4, np.array([10.0, 10.0, 50.0, 110.0]), 0.0, VClass.PERSON, 9, 12,
                          True)
    regions = redaction_regions([] + tracked_boxes([coasting]))
    assert regions == [(10, 10, 50, 110)]


def test_failsafe_mode_passes_only_hard_failures() -> None:
    seen = {}

    class Inner:
        stats: dict = {}

        def set_sim_time(self, t):
            pass

        def __call__(self, cfg, ctx):
            seen["conf"] = dict(ctx.confidence)

    ctx = JunctionContext(intersection_id="J", current_phase_id="P0",
                          current_phase_elapsed_s=3.0, has_demand={"L0": True, "L1": True},
                          wait_times_s={}, queue_pcu={"L0": 1.0, "L1": 1.0},
                          receiving_occupancy={}, receiving_queue_pcu={},
                          approaching_pcu={"L0": 0.0, "L1": 0.0})
    qs = {"queue_pcu": {}, "approaching_pcu": {}, "receiving_occupancy": {},
          "receiving_queue_pcu": {}, "confidence": {"L0": 0.7, "L1": 0.2}}
    VisionSensor(Inner(), _FakeLoop(qs), "J", "failsafe")(None, ctx)  # type: ignore[arg-type]
    assert seen["conf"] == {"L1": 0.2}  # 0.7 is uncertain but useful; 0.2 is a dead camera


def test_camera_passwords_stay_out_of_the_registry_and_the_logs(monkeypatch) -> None:
    from vision_service.sources import VideoSource, mask_uri

    assert mask_uri("rtsp://admin:hunter2@10.0.0.12:554/s1") == "rtsp://***@10.0.0.12:554/s1"
    assert mask_uri("clips/benz_circle.mp4") == "clips/benz_circle.mp4"
    # an @ in the path is not user-info
    assert mask_uri("http://host/path@x") == "http://host/path@x"
    monkeypatch.setenv("CAM_USER", "admin")
    monkeypatch.setenv("CAM_PASS", "hunter2")
    src = VideoSource("rtsp://${CAM_USER}:${CAM_PASS}@10.0.0.12/s1")
    assert src.uri == "rtsp://admin:hunter2@10.0.0.12/s1" and src.live
    assert "hunter2" not in src.shown


def test_a_slow_detector_gets_the_newest_frame_of_every_camera() -> None:
    from vision_service.main import LatestFrames

    latest = LatestFrames()
    latest.put("a", 1.0, "a1")
    latest.put("b", 1.1, "b1")
    latest.put("a", 1.2, "a2")          # the detector was busy: a1 is stale, skip it
    assert latest.take(0.0) == ("b", 1.1, "b1")   # oldest capture first: no camera starves
    assert latest.take(0.0) == ("a", 1.2, "a2")
    assert latest.take(0.0) is None and latest.dropped == 1


def test_the_service_defaults_to_the_adopted_detector(monkeypatch, tmp_path) -> None:
    import vision_service.main as vm
    from vision_service.simcam.errors import PRESETS

    assert vm.DEFAULT_PRESET == "itms6_640" and vm.DEFAULT_PRESET in PRESETS
    monkeypatch.setenv("VISION_DETECTOR", "yolo11n.pt")          # an explicit choice wins
    assert vm.detector_path() == "yolo11n.pt"
    monkeypatch.delenv("VISION_DETECTOR")
    monkeypatch.setattr(vm, "DEFAULT_DETECTOR", tmp_path / "missing.onnx")
    with pytest.raises(SystemExit, match="make vision-model"):   # no silent fallback
        vm.detector_path()
    (tmp_path / "missing.onnx").write_bytes(b"x")
    assert vm.detector_path() == str(tmp_path / "missing.onnx")


def test_a_box_on_a_barely_visible_vehicle_is_not_scored() -> None:
    from vision_service.eval.twin import _without_distractors

    scored_gt = np.array([[0, 0, 10, 10]], dtype=float)
    hidden_gt = np.array([[50, 0, 60, 10]], dtype=float)         # 80 % behind a bus
    boxes = np.array([[0, 0, 10, 10],                            # a hit
                      [50, 0, 60, 10],                           # the hidden one, tracked anyway
                      [100, 0, 110, 10]], dtype=float)           # nothing there: a real FP
    assert _without_distractors(boxes, scored_gt, hidden_gt).tolist() == [True, False, True]
    assert _without_distractors(boxes, scored_gt, np.zeros((0, 4))).all()


def test_messages_off_the_bus_are_read_and_a_backlog_is_skipped(network, rig, links) -> None:
    # through the real Avro encoding, where `occurred_at` decodes to a datetime
    import time as _time

    from itms_common.events import decode_envelope

    approach, receiving = links
    svc = VisionService(rig, approach, receiving, _Bus(), preset="ideal")
    pos = {"vehicle_id": "v1", "vehicle_type": "car", "lat": 16.5, "lon": 80.6,
           "speed_mps": 3.0, "heading_deg": 90.0, "edge_id": "in", "source": "sumo"}
    seen = []
    svc.on_vehicle_position = lambda t, payload: seen.append(payload)  # type: ignore[method-assign]
    env = decode_envelope(encode_envelope("VehiclePositionUpdated", "sim-service", pos))
    svc.on_envelope(1.0, env)
    assert len(seen) == 1                                           # fresh: used
    svc.on_envelope(2.0, env, wall_now=_time.time() + 60.0)
    assert len(seen) == 1                                           # a minute old: backlog
    sig = decode_envelope(encode_envelope("SignalChanged", "sim-service", {
        "intersection_id": "J", "phase_id": "P0", "source": "sumo"}))
    phases = []
    svc.on_signal_changed = lambda t, p: phases.append((t, p["phase_id"]))  # type: ignore
    svc.on_envelope(3.0, sig, wall_now=_time.time() + 3600.0)
    assert phases == [(3.0, "P0")]              # signal changes are replayed, whatever their age
