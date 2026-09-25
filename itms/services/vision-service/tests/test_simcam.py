"""SimCam films the right things, hides what is hidden, and its errors are
reproducible."""

from __future__ import annotations

import numpy as np
from vision_service.classes import ClassTable, VClass
from vision_service.simcam import (
    PRESETS,
    PerceptionErrorModel,
    WorldSnapshot,
    film,
    interpolate,
    snapshot_from_records,
)


def vehicles_on(network, lane_id: str, items, t: float = 0.0) -> WorldSnapshot:
    """`items`: (id, vclass, s_centre, speed). Positions given as centres."""
    lane = network.lanes[lane_id]
    recs = []
    for vid, vc, s, v in items:
        xy = lane.point_at(s)[0]
        recs.append({"id": vid, "vclass": vc, "x": xy[0], "y": xy[1],
                     "heading": float(lane.heading_at(s)[0]), "speed": v, "lane_id": lane_id})
    return snapshot_from_records(t, recs, ClassTable.default(), position_is_front=False)


def test_front_bumper_is_converted_to_centre(network) -> None:
    snap = snapshot_from_records(0.0, [{"id": "a", "vclass": VClass.CAR, "x": 100.0,
                                        "y": 0.0, "heading": 90.0, "speed": 0.0}],
                                 ClassTable.default())
    assert snap.xy[0, 0] < 100.0  # centre is behind the front bumper when driving east


def test_a_vehicle_on_the_approach_is_filmed(network, camera) -> None:
    snap = vehicles_on(network, "in_0", [("a", VClass.CAR, 150.0, 5.0)])
    f = film(camera, snap)
    assert f.ids == ("a",) and f.visible[0] == 1.0
    x1, y1, x2, y2 = f.boxes[0]
    assert 0 <= x1 < x2 <= camera.width_px and 0 <= y1 < y2 <= camera.height_px


def test_behind_the_camera_is_not_filmed(network, camera) -> None:
    snap = vehicles_on(network, "out_0", [("a", VClass.CAR, 100.0, 5.0)])
    assert len(film(camera, snap)) == 0


def test_a_bus_hides_the_motorcycle_behind_it(network, camera) -> None:
    # bus nearer the camera (larger s = closer to the stop line), motorcycle behind it
    snap = vehicles_on(network, "in_0", [("bus", VClass.BUS, 170.0, 0.0),
                                        ("moto", VClass.MOTORCYCLE, 158.0, 0.0)])
    f = film(camera, snap)
    vis = dict(zip(f.ids, f.visible, strict=True))
    assert vis["bus"] == 1.0
    assert vis["moto"] < 0.5


def test_interpolation_moves_linearly_and_takes_the_short_way_round(network) -> None:
    a = vehicles_on(network, "in_0", [("a", VClass.CAR, 100.0, 10.0)], t=0.0)
    b = vehicles_on(network, "in_0", [("a", VClass.CAR, 110.0, 10.0)], t=1.0)
    mid = interpolate(a, b, 0.5)
    np.testing.assert_allclose(mid.xy[0], (a.xy[0] + b.xy[0]) / 2)
    h1 = WorldSnapshot(0, ("x",), (VClass.CAR,), np.zeros((1, 2)), np.array([350.0]),
                       np.ones(1), np.ones(1), np.ones(1), np.zeros(1), ("",), np.zeros(1))
    h2 = WorldSnapshot(1, ("x",), (VClass.CAR,), np.zeros((1, 2)), np.array([10.0]),
                       np.ones(1), np.ones(1), np.ones(1), np.zeros(1), ("",), np.zeros(1))
    assert interpolate(h1, h2, 0.5).heading[0] == 0.0


def test_ideal_detects_everything_visible(network, camera) -> None:
    snap = vehicles_on(network, "in_0", [(f"v{i}", VClass.CAR, 120.0 + 12 * i, 0.0)
                                        for i in range(4)])
    f = film(camera, snap)
    dets = PerceptionErrorModel("ideal", seed=1).detect(camera, f)
    assert sorted(str(d.truth_id) for d in dets) == sorted(f.ids)


def test_errors_are_reproducible_per_seed_and_camera(network, camera) -> None:
    snap = vehicles_on(network, "in_0", [(f"v{i}", VClass.MOTORCYCLE, 60.0 + 9 * i, 0.0)
                                        for i in range(10)])
    f = film(camera, snap)

    def run(seed, cid):
        m = PerceptionErrorModel("coco_pretrained", seed=seed, camera_id=cid)
        return [(d.truth_id, d.vclass, round(d.box[0], 6)) for _ in range(5)
                for d in m.detect(camera, f)]

    assert run(3, "c") == run(3, "c")
    assert run(3, "c") != run(4, "c")


def test_coco_preset_mislabels_auto_rickshaws(network, camera) -> None:
    snap = vehicles_on(network, "in_0", [(f"a{i}", VClass.AUTO_RICKSHAW, 110.0 + 9 * i, 0.0)
                                        for i in range(8)])
    f = film(camera, snap)
    m = PerceptionErrorModel("coco_pretrained", seed=0)
    labels = [d.vclass for _ in range(30) for d in m.detect(camera, f) if d.truth_id]
    share_auto = sum(lb is VClass.AUTO_RICKSHAW for lb in labels) / len(labels)
    assert share_auto < 0.6  # most are called car or motorcycle


def test_presets_get_worse_in_the_intended_order() -> None:
    fd, cp, nr = PRESETS["finetuned_day"], PRESETS["coco_pretrained"], PRESETS["night_rain"]
    assert fd.base_recall[VClass.MOTORCYCLE] > cp.base_recall[VClass.MOTORCYCLE]
    assert nr.size_h50_px > fd.size_h50_px and nr.fp_per_frame > fd.fp_per_frame


def test_hotspots_sit_by_the_kerb(network, rig, camera) -> None:
    m = PerceptionErrorModel("coco_pretrained", seed=5, camera_id="camJ")
    cov = rig.coverage_by_camera["camJ"]
    m.place_hotspots([network.lanes[lid] for lid in cov], cov)
    assert m._hotspots
    for hs in m._hotspots:
        dists = [abs(network.lanes[lid].project(hs.box_ground_xy[None])[1][0]) for lid in cov]
        assert min(dists) >= network.lanes["in_0"].width / 2.0


def test_the_error_model_forgets_vehicles_long_gone(network, camera) -> None:
    from vision_service.simcam.errors import _PRUNE_EVERY

    m = PerceptionErrorModel("coco_pretrained", seed=3, camera_id="camJ")
    for k in range(3 * _PRUNE_EVERY):   # a new auto-rickshaw every 50 frames, for 30 minutes
        vid = f"v{k // 50}"
        m.detect(camera, film(camera, vehicles_on(network, "in_0",
                                                  [(vid, VClass.AUTO_RICKSHAW, 150.0, 0.0)])))
    assert len(m._bad) <= 2 * _PRUNE_EVERY // 50 + 1
    assert set(m._label) <= set(m._bad) and "v0" not in m._bad
