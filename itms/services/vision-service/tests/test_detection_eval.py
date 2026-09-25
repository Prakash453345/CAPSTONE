"""Still-image detector evaluation (`vision_service.eval.detection`)."""

from __future__ import annotations

import pytest
from vision_service.classes import VClass
from vision_service.eval.detection import DetectionEval, average_precision

CAR, AUTO, BIKE = VClass.CAR, VClass.AUTO_RICKSHAW, VClass.MOTORCYCLE


def test_average_precision_reference_values() -> None:
    assert average_precision([0.9, 0.8], [True, True], 2) == pytest.approx(1.0)
    assert average_precision([0.9], [True], 2) == pytest.approx(0.5)
    # a false positive ranked first costs precision at every recall level
    assert average_precision([0.9, 0.8], [False, True], 1) == pytest.approx(0.5)
    assert average_precision([], [], 3) == 0.0


def test_a_wrong_type_is_found_but_not_correct_and_costs_its_pcu_difference() -> None:
    ev = DetectionEval()
    ev.add([[0, 0, 10, 20], [50, 0, 60, 20]], [AUTO, CAR],
           [[0, 0, 10, 20], [50, 0, 60, 20]], [0.9, 0.9], [CAR, CAR])
    s = ev.summary()
    auto = s["per_class"]["auto_rickshaw"]
    assert auto["recall"] == 0.0 and auto["found_as_some_vehicle"] == 1.0
    assert auto["reported_as"] == {"car": 1}
    assert s["per_class"]["car"]["precision"] == pytest.approx(0.5)  # one of two "cars" was an auto
    assert s["vehicle_recall"] == 1.0 and s["false_pos_per_image"] == 0.0
    assert s["pcu_per_image"]["bias"] == pytest.approx(1.0 + 1.0 - (0.6 + 1.0))


def test_misses_ghosts_and_the_operating_threshold() -> None:
    ev = DetectionEval(op_thresh=0.5)
    ev.add([[0, 0, 10, 20], [50, 0, 60, 20]], [CAR, BIKE],
           [[0, 0, 10, 20], [50, 0, 60, 20], [200, 200, 220, 230]],
           [0.9, 0.3, 0.8], [CAR, BIKE, CAR])
    s = ev.summary()
    # the bike box scored 0.3: below the tracker's line, so a miss at the operating point ...
    assert s["per_class"]["motorcycle"]["reported_as"] == {"missed": 1}
    # ... but it still counts toward the threshold-free AP
    assert s["per_class"]["motorcycle"]["ap50"] == pytest.approx(1.0)
    assert s["false_pos_by_class"] == {"car": 1}
    assert s["vehicle_recall"] == pytest.approx(0.5)
    assert s["vehicle_precision"] == pytest.approx(0.5)


def test_detections_on_an_ignore_region_are_neither_hits_nor_ghosts() -> None:
    """UVH-26's "Others" maps to no ITMS class: a detector that boxes one
    is not wrong, and must not be charged a false positive."""
    ev = DetectionEval()
    ev.add([[0, 0, 10, 20], [100, 100, 130, 140]], [CAR, None],
           [[0, 0, 10, 20], [100, 100, 130, 140]], [0.9, 0.9], [CAR, CAR])
    s = ev.summary()
    assert s["vehicles"] == 1 and s["false_pos_per_image"] == 0.0
    assert s["ignored_detections"] == 1
    assert s["per_class"]["car"]["ap50"] == pytest.approx(1.0)
    assert s["pcu_per_image"]["bias"] == 0.0


def test_recall_by_box_height() -> None:
    ev = DetectionEval()
    ev.add([[0, 0, 10, 15], [50, 0, 60, 100]], [CAR, CAR],
           [[50, 0, 60, 100]], [0.9], [CAR])
    by = ev.summary()["recall_by_height"]
    assert by["0-20px"] == (0.0, 1) and by["80-infpx"] == (1.0, 1)
