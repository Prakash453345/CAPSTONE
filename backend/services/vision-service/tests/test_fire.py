"""Fire and smoke: crop preprocessing, the persistence layer, and the
service publishing a candidate. Model-based parity checks are skipped unless
the model files are present (they are not in git)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
from itms_common.events import decode_envelope, encode_envelope
from vision_service.events import fire_payload
from vision_service.fire import FireMonitor, FireMonitorConfig
from vision_service.fire.classifier import CROP, crop_box, softmax, to_input
from vision_service.fire.detector import P_FIRE, P_SMOKE, FireScore
from vision_service.service import VisionService

from tests.test_service_and_io import _Bus


def alarm(p_fire=0.9, p_smoke=0.0) -> FireScore:
    return FireScore(p_fire, p_smoke, (10.0, 20.0, 50.0, 60.0) if p_fire else None,
                     (5.0, 5.0, 90.0, 90.0) if p_smoke else None, (100, 100), 2)


def quiet() -> FireScore:
    return FireScore(0.1, 0.1, None, None, (100, 100), 1)


# ---- thresholds and one frame ------------------------------------------------------------

def test_a_frame_alarms_on_either_class_at_its_own_threshold() -> None:
    assert P_FIRE == 0.80 and P_SMOKE == 0.90    # the values Step 2 chose on validation
    assert FireScore(0.80, 0.0).alarm and not FireScore(0.79, 0.0).alarm
    assert FireScore(0.0, 0.90).alarm and not FireScore(0.0, 0.89).alarm
    assert not FireScore(0.85, 0.85).smoke_alarm and FireScore(0.85, 0.85).fire_alarm


# ---- preprocessing -------------------------------------------------------------------------

def test_crop_grows_the_box_by_a_quarter_and_clips_to_the_frame() -> None:
    pytest.importorskip("cv2")
    frame = np.zeros((200, 300, 3), np.uint8)
    frame[40:80, 100:160] = 255            # the box: 60 wide, 40 high
    out = crop_box(frame, (100, 40, 160, 80))
    assert out.shape == (CROP, CROP, 3)
    # grown by 15 px sideways and 10 px up/down: the border of the crop is black, the middle white
    assert out[CROP // 2, CROP // 2].min() == 255 and out[0, 0].max() == 0
    edge = crop_box(frame, (-20, -20, 30, 30))   # off the frame: clipped, not a crash
    assert edge.shape == (CROP, CROP, 3)
    assert crop_box(frame, (500, 500, 510, 510)).shape == (CROP, CROP, 3)   # nothing left: zeros


def test_input_is_rgb_normalised_channels_first() -> None:
    bgr = np.zeros((1, CROP, CROP, 3), np.uint8)
    bgr[..., 2] = 255                      # pure red in BGR order
    x = to_input(bgr)
    assert x.shape == (1, 3, CROP, CROP) and x.dtype == np.float32
    assert x[0, 0, 0, 0] == pytest.approx((1.0 - 0.485) / 0.229, rel=1e-5)     # R channel first
    assert x[0, 2, 0, 0] == pytest.approx((0.0 - 0.406) / 0.225, rel=1e-5)
    p = softmax(np.array([[2.0, 1.0, 0.0]]))
    assert p.sum() == pytest.approx(1.0) and p.argmax() == 0


# ---- persistence ----------------------------------------------------------------------------

def run(mon: FireMonitor, seq: list[tuple[float, FireScore]]):
    for t, s in seq:
        mon.observe(t, s)
    return mon.drain()


def test_one_alarming_frame_is_not_a_candidate() -> None:
    new, _ = run(FireMonitor("c"), [(0, quiet()), (1, alarm()), (2, quiet()), (3, quiet())])
    assert new == []


def test_three_alarms_in_five_raise_one_candidate_and_it_keeps_the_first_alarm_time() -> None:
    mon = FireMonitor("cam1")
    new, _ = run(mon, [(0, quiet()), (1, alarm()), (2, quiet()), (3, alarm()), (4, alarm())])
    assert len(new) == 1
    c = new[0]
    assert c.camera_id == "cam1" and c.kind == "fire" and c.first_t == 1 and c.raised_t == 4
    assert c.score == pytest.approx(0.9) and c.evidence["box_norm"] == [0.1, 0.2, 0.5, 0.6]
    more, _ = run(mon, [(5, alarm()), (6, alarm())])
    assert more == []                      # still the same candidate


def test_kind_follows_what_alarmed_and_score_is_the_highest() -> None:
    mon = FireMonitor("c")
    run(mon, [(0, alarm(0.85, 0.0)), (1, alarm(0.0, 0.95)), (2, alarm(0.9, 0.0))])
    c = mon.active
    assert c is not None and c.kind == "fire+smoke" and c.score == pytest.approx(0.95)


def test_candidate_resolves_after_clear_s_without_an_alarm_then_cools_down() -> None:
    cfg = FireMonitorConfig(clear_s=30.0, cooldown_s=120.0)
    mon = FireMonitor("c", cfg)
    run(mon, [(0, alarm()), (1, alarm()), (2, alarm())])
    assert mon.active is not None
    _, res = run(mon, [(20, quiet()), (31, quiet())])
    assert res == []                       # only 29 s since the last alarm
    _, res = run(mon, [(32, quiet())])
    assert len(res) == 1 and res[0].status == "RESOLVED" and res[0].resolved_t == 32
    new, _ = run(mon, [(40, alarm()), (41, alarm()), (42, alarm())])
    assert new == []                       # cooling down until 152
    new, _ = run(mon, [(160, alarm()), (161, alarm()), (162, alarm())])
    assert len(new) == 1


def test_a_gap_in_the_video_does_not_join_alarms_from_both_sides() -> None:
    mon = FireMonitor("c", FireMonitorConfig(max_gap_s=10.0))
    new, _ = run(mon, [(0, alarm()), (1, alarm()), (60, alarm())])
    assert new == []
    new, _ = run(mon, [(61, alarm()), (62, alarm())])
    assert len(new) == 1


# ---- the service ----------------------------------------------------------------------------

def test_service_publishes_an_unconfirmed_fire_candidate_on_the_anomaly_topic(
        rig, links, monkeypatch) -> None:
    bus = _Bus()
    approach, receiving = links
    svc = VisionService(rig, approach, receiving, bus, preset="ideal", fire=FireMonitorConfig())
    clock = {"now": 2_000_000.0}
    monkeypatch.setattr("vision_service.service.time.time", lambda: clock["now"])
    for t in (0.0, 1.0, 2.0):
        svc.on_fire_score("camJ", t, alarm())
    clock["now"] += 2.0
    svc.tick(2.0)
    ups = [e[2] for e in bus.events if e[1] == "AnomalyUpdated"]
    assert len(ups) == 1
    u = ups[0]
    assert u["source"] == "VISION" and u["anomaly_type"] == "fire" and u["status"] == "ACTIVE"
    assert u["edge_id"] == "in" and u["estimated_impact"] == 0.0 and u["severity"] == "high"
    assert u["start_time_ms"] == (2_000_000 + 2 - 2) * 1000     # the first alarming frame's time
    detail = json.loads(u["detail"])
    assert detail["rule"] == "fire_smoke" and detail["camera"] == "camJ"
    # resolves later, keeping its start time
    for t in (3.0, 40.0):
        svc.on_fire_score("camJ", t, quiet())
    clock["now"] += 40.0
    svc.tick(40.0)
    ups = [e[2] for e in bus.events if e[1] == "AnomalyUpdated"]
    assert [x["status"] for x in ups] == ["ACTIVE", "RESOLVED"]
    assert ups[0]["start_time_ms"] == ups[1]["start_time_ms"]
    assert ups[0]["anomaly_id"] == ups[1]["anomaly_id"]


def test_fire_is_off_unless_configured(rig, links) -> None:
    bus = _Bus()
    approach, receiving = links
    svc = VisionService(rig, approach, receiving, bus, preset="ideal")
    for t in (0.0, 1.0, 2.0):
        svc.on_fire_score("camJ", t, alarm())
    svc.tick(2.0)
    assert not [e for e in bus.events if e[1] == "AnomalyUpdated"]


def test_fire_payload_satisfies_the_avro_contract() -> None:
    mon = FireMonitor("cam9")
    run(mon, [(0, alarm()), (1, alarm()), (2, alarm())])
    out = decode_envelope(encode_envelope("AnomalyUpdated", "pytest", fire_payload(
        mon.active, edge_id="in")))["payload"]  # type: ignore[arg-type]
    assert out["anomaly_type"] == "fire" and out["source"] == "VISION"


# ---- the real models (skipped when the files are not here) --------------------------------

_DET = os.environ.get("VISION_FIRE_DETECTOR", "")
_CLS = os.environ.get("VISION_FIRE_CLASSIFIER", "")
_FRAME = os.environ.get("VISION_FIRE_PARITY_FRAME", "")


@pytest.mark.skipif(not (Path(_DET).is_file() and Path(_CLS).is_file() and Path(_FRAME).is_file()),
                    reason="needs VISION_FIRE_DETECTOR, VISION_FIRE_CLASSIFIER and a frame")
def test_scorer_reproduces_the_step2_notebook_on_its_b4_alarm_frame() -> None:
    """`147883.jpg` (Bengaluru, night) alarmed in the Step 2 run with
    p_fire 0.8647; the same pipeline here must give the same number."""
    import cv2
    from vision_service.fire.detector import FireScorer

    sc = FireScorer(_DET, _CLS).score(cv2.imread(_FRAME))
    assert sc.p_fire == pytest.approx(0.8647, abs=2e-3) and sc.p_smoke == 0.0 and sc.alarm


def test_fire_models_in_data_models_are_used_by_default(monkeypatch, tmp_path):
    from vision_service import main as vm

    det, cls = tmp_path / "d.pt", tmp_path / "c.onnx"
    monkeypatch.setattr(vm, "DEFAULT_FIRE_DETECTOR", det)
    monkeypatch.setattr(vm, "DEFAULT_FIRE_CLASSIFIER", cls)
    for k in ("VISION_FIRE", "VISION_FIRE_DETECTOR", "VISION_FIRE_CLASSIFIER"):
        monkeypatch.delenv(k, raising=False)
    assert vm.fire_paths() is None                      # neither file: no fire detection
    det.write_bytes(b"x")
    assert vm.fire_paths() is None                      # one file is not enough
    cls.write_bytes(b"x")
    assert vm.fire_paths() == (str(det), str(cls))      # both: on
    monkeypatch.setenv("VISION_FIRE", "0")
    assert vm.fire_paths() is None                      # explicit off
