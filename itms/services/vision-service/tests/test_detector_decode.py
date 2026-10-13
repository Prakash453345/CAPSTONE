"""Decoding a YOLO head in the ITMS taxonomy (`vision_service.detect.yolo`),
without torch or ONNX Runtime: synthetic head outputs."""

from __future__ import annotations

import numpy as np
import pytest
from vision_service.classes import VClass
from vision_service.detect.yolo import class_map_for, decode, merge_matrix

# a UVH-26-like head: two car types, a two-wheeler, and a class the taxonomy drops
NAMES = ["Sedan", "Hatchback", "Two-wheeler", "Others"]


def _head(rows: list[tuple[tuple[float, float, float, float], list[float]]]) -> np.ndarray:
    """(cx, cy, w, h) + per-class scores per candidate -> a (4 + C, N) head."""
    return np.array([[*box, *scores] for box, scores in rows], dtype=np.float32).T


def test_merge_matrix_only_for_many_to_one_maps() -> None:
    assert merge_matrix(class_map_for(["car", "bus"] + ["x"] * 78), 80) is None  # not COCO: by name
    groups, m = merge_matrix(class_map_for(NAMES), len(NAMES))
    assert groups == [VClass.CAR, VClass.MOTORCYCLE]
    assert m.tolist() == [[1, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]


def test_a_car_split_across_types_is_one_confident_car() -> None:
    """0.45 sedan + 0.40 hatchback is a car at 0.85 -- not a car at 0.45
    that ByteTrack's 0.5 line would drop, and not two boxes that survive
    NMS as two types."""
    head = _head([
        ((100, 100, 40, 30), [0.45, 0.40, 0.0, 0.0]),
        ((101, 100, 40, 30), [0.10, 0.55, 0.0, 0.0]),   # the same car, other type on top
        ((300, 100, 20, 30), [0.0, 0.0, 0.6, 0.0]),
    ])
    dets = decode(head, class_map_for(NAMES), conf=0.5, iou=0.6, r=1.0, pad=(0, 0))
    cars = [d for d in dets if d.vclass is VClass.CAR]
    assert len(cars) == 1 and cars[0].score == pytest.approx(0.85)
    assert [d.vclass for d in dets if d.vclass is not VClass.CAR] == [VClass.MOTORCYCLE]


def test_a_box_the_dropped_class_wins_is_dropped() -> None:
    head = _head([((100, 100, 40, 30), [0.3, 0.1, 0.0, 0.9])])
    assert decode(head, class_map_for(NAMES), conf=0.1, iou=0.6, r=1.0, pad=(0, 0)) == []


def test_a_one_to_one_map_decodes_by_best_class_and_undoes_the_letterbox() -> None:
    names = ["person", "bicycle", "car"]
    head = _head([((110, 70, 40, 20), [0.1, 0.2, 0.7])])
    (d,) = decode(head, class_map_for(names), conf=0.5, iou=0.6, r=0.5, pad=(10, 20))
    assert d.vclass is VClass.CAR and d.score == pytest.approx(0.7)
    assert d.box == pytest.approx((160.0, 80.0, 240.0, 120.0))  # ((cx -+ w/2) - pad) / r


def test_batchnorm_health_finds_broken_and_clipped_statistics() -> None:
    torch = pytest.importorskip("torch")
    from vision_service.detect.yolo import batchnorm_health

    net = torch.nn.Sequential(torch.nn.Conv2d(3, 4, 1), torch.nn.BatchNorm2d(4),
                              torch.nn.BatchNorm2d(4))
    assert batchnorm_health(net) == {"channels": 8, "nonfinite": 0, "at_fp16_max": 0}
    net[1].running_var[0] = float("inf")        # IISc's release: stored as infinity
    net[1].running_mean[1] = float("nan")
    net[2].running_var[:2] = 65504.0            # a half-precision save of a larger variance
    net[2].running_var[3] = 2.4e7               # large but intact (a full-precision file)
    assert batchnorm_health(net) == {"channels": 8, "nonfinite": 2, "at_fp16_max": 2}


def test_the_ultralytics_detector_warns_about_broken_statistics(monkeypatch, caplog) -> None:
    import logging
    import sys
    import types

    torch = pytest.importorskip("torch")
    from vision_service.detect.yolo import UltralyticsDetector

    class FakeYOLO:
        def __init__(self, weights):
            self.model = torch.nn.Sequential(torch.nn.Conv2d(3, 4, 1), torch.nn.BatchNorm2d(4))
            self.model.stride = torch.tensor([32.0])
            if "broken" in weights:
                self.model[1].running_var[0] = float("inf")
            self.names = {0: "car"}

    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=FakeYOLO))
    with caplog.at_level(logging.WARNING, logger="vision.detect"):
        ok = UltralyticsDetector("fine.pt")
        assert ok.bn_health["nonfinite"] == 0 and not caplog.records
        bad = UltralyticsDetector("broken.pt")
    assert bad.bn_health["nonfinite"] == 1
    assert "non-finite statistics" in caplog.records[0].getMessage()
