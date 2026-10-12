"""Uploaded-clip incident detection: severity rules, the screen-space motion
checks, the accident alarm rule, the analysis that combines them, and the
worker end to end on a real (synthetic) video file. No model files needed --
detectors are fakes with the real interfaces."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from itms_common.events import decode_envelope, encode_envelope
from vision_service.classes import VClass
from vision_service.clips.accident import DEFAULT_RULE, AccidentAlarm, AlarmRule
from vision_service.clips.analyse import ClipDetectors, analyse_clip
from vision_service.clips.motion import JAM_MIN_S, STALL_S, MotionAnalyser
from vision_service.clips.severity import SecondStats, assess
from vision_service.clips.worker import ClipWorker, analysed_payload
from vision_service.fire.detector import FireScore
from vision_service.records import ImageTrack

# ---------------------------------------------------------------- severity


def scene(seconds: int, vehicles: int, moving: int, stopped: int) -> list[SecondStats]:
    return [SecondStats(float(t), vehicles, moving, stopped) for t in range(seconds)]


def test_severity_starts_from_the_type():
    flowing = scene(60, 8, 6, 1)
    assert assess("fire", 5, 30, flowing).level == "high"
    assert assess("accident", 5, 30, flowing).level == "high"
    assert assess("vehicle_breakdown", 5, 30, flowing).level == "medium"
    assert assess("heavy_congestion", 5, 30, flowing).level == "low"


def test_traffic_stopping_after_an_accident_makes_it_blocked():
    sev = assess("accident", 5, 30, scene(60, 9, 0, 9))
    assert sev.level == "blocked"
    assert any("stopped" in r for r in sev.reasons)


def test_a_stalled_vehicle_with_a_queue_is_high_but_congestion_never_passes_medium():
    assert assess("vehicle_breakdown", 0, 30, scene(60, 8, 3, 6)).level == "high"
    assert assess("vehicle_breakdown", 0, 100, scene(120, 4, 3, 1)).level == "high"
    jam = assess("heavy_congestion", 0, 200, scene(200, 40, 0, 40))
    assert jam.level == "medium"


def test_without_a_vehicle_detector_severity_is_the_types_and_says_so():
    sev = assess("vehicle_breakdown", 0, 30, None)
    assert sev.level == "medium"
    assert any("no vehicle detector" in r for r in sev.reasons)


# ---------------------------------------------------------------- motion


def track(tid: int, x: float, y: float, h: float = 40.0) -> ImageTrack:
    return ImageTrack(track_id=tid, box=np.array([x - 20, y - h, x + 20, y]), score=0.9,
                      vclass=VClass.CAR, hits=10, age_frames=10, coasting=False)


def run(frames: list[tuple[float, list[ImageTrack]]]):
    m = MotionAnalyser()
    for t, tracks in frames:
        m.observe(t, tracks, (1280, 720))
    return m, m.finish()


def stall_clip(passers_dx: float, passers_dy: float, *, drives_in: bool = True):
    """Track 1 drives right for 4 s (or not), then stands 40 s at x=400 while
    a new vehicle crosses the frame along (dx, dy) every 4 s."""
    frames = []
    for i in range(int(44 * 5)):
        t = i / 5
        x1 = (100 + 75 * t if t < 4 else 400) if drives_in else 400
        tracks = [track(1, x1, 500)]
        k = int(t // 4)                              # a new passer every 4 s
        dt_ = t - 4 * k
        tracks.append(track(100 + k, 50 + passers_dx * 60 * dt_, 300 + passers_dy * 60 * dt_))
        frames.append((t, tracks))
    return run(frames)


def test_a_vehicle_that_stops_while_its_own_traffic_passes_is_stalled():
    _, findings = stall_clip(1.0, 0.0)
    stalled = [f for f in findings if f.detector == "stalled"]
    assert len(stalled) == 1
    f = stalled[0]
    assert f.anomaly_type == "vehicle_breakdown"
    assert 3.0 <= f.start_s <= 6.0                  # it stopped at 4 s
    assert f.end_s - f.start_s >= STALL_S
    assert f.evidence["passed_by"] >= 2
    assert f.box_norm is not None


def test_a_queue_at_a_red_light_with_cross_traffic_moving_is_not_stalled():
    _, findings = stall_clip(0.0, 1.0)              # passers move down: cross traffic
    assert not [f for f in findings if f.detector == "stalled"]


def test_a_vehicle_parked_from_the_start_is_not_stalled():
    _, findings = stall_clip(1.0, 0.0, drives_in=False)
    assert not [f for f in findings if f.detector == "stalled"]


def jam_clip(seconds: float):
    frames = []
    for i in range(int(seconds * 5)):
        t = i / 5
        frames.append((t, [track(k, 60 + 90 * (k % 12), 200 + 40 * (k // 12)) for k in range(14)]))
    return run(frames)


def test_a_long_standstill_with_many_vehicles_is_heavy_congestion():
    m, findings = jam_clip(JAM_MIN_S + 15)
    jams = [f for f in findings if f.detector == "congestion"]
    assert len(jams) == 1
    assert jams[0].evidence["mean_vehicles"] == 14
    assert m.seconds and m.seconds[-1].stopped == 14


def test_a_standstill_as_short_as_a_red_light_is_not_congestion():
    _, findings = jam_clip(40)
    assert not [f for f in findings if f.detector == "congestion"]


# ---------------------------------------------------------------- accident alarm


def test_the_accident_alarm_needs_k_of_the_last_n_frames():
    alarm = AccidentAlarm(AlarmRule(0.6, 3, 5, validated=True))
    probs = [0.1, 0.7, 0.2, 0.8, 0.1, 0.1, 0.9, 0.95, 0.7, 0.2, 0.1, 0.1, 0.1, 0.1]
    for i, p in enumerate(probs):
        alarm.observe(i * 0.5, p)
    assert len(alarm.runs) == 1
    run_ = alarm.runs[0]
    assert run_["alarm_s"] == 3.5                   # the 3rd hot frame of 0.7/0.8/0.9 within 5
    assert run_["start_s"] == 1.5                   # first hot frame in that window
    assert run_["peak"] == 0.95


def test_the_alarm_rule_is_read_from_beside_the_model_or_marked_unvalidated(tmp_path):
    model = tmp_path / "itms_accident_224.onnx"
    model.write_bytes(b"")
    default = AlarmRule.for_model(model)
    assert (default.thr, default.k, default.n) == (DEFAULT_RULE["thr"], DEFAULT_RULE["k"],
                                                   DEFAULT_RULE["n"])
    assert not default.validated
    (tmp_path / "chosen_in_distribution.json").write_text(json.dumps(
        {"variant": "real_only", "thr": 0.65, "k": 3, "n": 4}))
    chosen = AlarmRule.for_model(model)
    assert (chosen.thr, chosen.k, chosen.n, chosen.validated) == (0.65, 3, 4, True)


# ---------------------------------------------------------------- analysis


class FakeAccident:
    """P(accident) by time: high from `from_s` on."""

    def __init__(self, from_s: float | None, rule=None):
        self.from_s = from_s
        self.rule = rule or AlarmRule(0.5, 3, 5, validated=True)
        self.seen: list[float] = []

    def prob(self, frame: np.ndarray) -> float:
        t = float(frame[0, 0, 0])                    # the fake video stamps its time here
        self.seen.append(t)
        return 0.9 if self.from_s is not None and t >= self.from_s else 0.05


class FakeFire:
    def __init__(self, from_s: float | None):
        self.from_s = from_s

    def score(self, frame: np.ndarray) -> FireScore:
        t = float(frame[0, 0, 0])
        if self.from_s is not None and t >= self.from_s:
            return FireScore(0.95, 0.1, (10.0, 10.0, 50.0, 50.0), None, (100, 100), 1)
        return FireScore(0.05, 0.05, None, None, (100, 100), 0)


def fake_frames(seconds: float, fps: float = 10.0):
    for i in range(int(seconds * fps)):
        t = i / fps
        frame = np.zeros((100, 100, 3), dtype=np.float32)
        frame[0, 0, 0] = t
        yield t, frame


def test_a_clip_with_no_detector_cannot_be_analysed():
    with pytest.raises(ValueError):
        analyse_clip(fake_frames(5), ClipDetectors())


def test_normal_traffic_gives_no_finding_and_names_the_detectors_that_looked():
    result = analyse_clip(fake_frames(20), ClipDetectors(accident=FakeAccident(None),
                                                         fire=FakeFire(None)))
    assert result.main is None
    assert result.detectors == ["fire", "accident"]
    assert len(result.timeline["t"]) == 20 and max(result.timeline["accident"]) < 0.5


def test_an_accident_is_found_where_it_happens_and_rated_from_its_type():
    acc = FakeAccident(10.0)
    result = analyse_clip(fake_frames(30), ClipDetectors(accident=acc))
    assert acc.seen[:4] == [0.0, 0.5, 1.0, 1.5]     # sampled at 2 fps, its training rate
    main = result.main
    assert main is not None and main.anomaly_type == "accident"
    assert 10.0 <= main.start_s <= 11.0
    assert main.severity == "high" and main.confidence == 0.9
    assert main.reasons[0].startswith("accident model: 3 of 5 frames")
    assert any("no vehicle detector" in r for r in main.reasons)


def test_an_unvalidated_alarm_rule_is_called_out_to_the_reviewer():
    acc = FakeAccident(5.0, AlarmRule(0.5, 3, 5, validated=False))
    main = analyse_clip(fake_frames(20), ClipDetectors(accident=acc)).main
    assert main is not None and "not validated" in main.reasons[0]


def test_fire_outranks_an_accident_of_the_same_severity():
    result = analyse_clip(fake_frames(30), ClipDetectors(accident=FakeAccident(5.0),
                                                         fire=FakeFire(15.0)))
    assert [f.anomaly_type for f in result.findings] == ["fire", "accident"]
    assert result.main is not None and result.main.box_norm == (0.1, 0.1, 0.5, 0.5)


# ---------------------------------------------------------------- worker, on a real file


def write_video(path: Path, seconds: float, fps: float = 10.0) -> None:
    cv2 = pytest.importorskip("cv2")
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (160, 120))
    for i in range(int(seconds * fps)):
        frame = np.full((120, 160, 3), 40 if i / fps < 8 else 220, dtype=np.uint8)
        out.write(frame)
    out.release()


class BrightnessAccident:
    """P(accident) high once the video turns bright (8 s in)."""

    rule = AlarmRule(0.5, 3, 5, validated=True)

    def prob(self, frame: np.ndarray) -> float:
        return 0.9 if frame.mean() > 128 else 0.05


def test_the_worker_analyses_a_video_file_and_publishes_an_encodable_result(tmp_path):
    clip_dir = tmp_path / "clip-1"
    clip_dir.mkdir()
    video = clip_dir / "source.avi"
    write_video(video, 16)
    published: list[dict] = []
    worker = ClipWorker(ClipDetectors(accident=BrightnessAccident()), published.append)

    final = worker.handle({"clip_id": "clip-1", "video_path": str(video)})

    assert published[0]["status"] == "ANALYSING"
    assert final["status"] == "DONE" and published[-1] == final
    assert final["anomaly_type"] == "accident" and final["severity"] == "high"
    assert 7.5 <= final["flagged_at_s"] <= 9.0
    assert 15.0 <= final["duration_s"] <= 16.5
    assert Path(final["snapshot_path"]).exists()
    assert json.loads((clip_dir / "result.json").read_text()) == final
    findings = json.loads(final["findings_json"])
    assert findings[0]["detector"] == "accident"
    # the wire contract accepts it
    env = decode_envelope(encode_envelope("ClipAnalysed", source="test", payload=final))
    assert env["payload"]["anomaly_type"] == "accident"

    published.clear()                                # a second delivery is not re-analysed
    again = worker.handle({"clip_id": "clip-1", "video_path": str(video)})
    assert again == final and published == [final]


def test_a_file_that_is_not_a_video_fails_cleanly(tmp_path):
    clip_dir = tmp_path / "clip-2"
    clip_dir.mkdir()
    bad = clip_dir / "source.mp4"
    bad.write_bytes(b"not a video")
    published: list[dict] = []
    final = ClipWorker(ClipDetectors(accident=BrightnessAccident()), published.append).handle(
        {"clip_id": "clip-2", "video_path": str(bad)})
    assert final["status"] == "FAILED" and "cannot open" in final["error"]
    assert final["anomaly_type"] is None
    encode_envelope("ClipAnalysed", source="test", payload=final)


def test_a_progress_payload_round_trips_through_the_contract():
    p = analysed_payload("c", "ANALYSING", progress=0.4, now_ms=1_700_000_000_000)
    env = decode_envelope(encode_envelope("ClipAnalysed", source="test", payload=p))
    assert env["payload"]["progress"] == pytest.approx(0.4)
    assert env["payload"]["findings_json"] == "[]"
