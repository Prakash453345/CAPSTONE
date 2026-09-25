"""A small synthetic road and camera, so every stage can be tested without
SUMO or the Vijayawada net.

    x = 0 ............................ 200 | junction J | 215 ............. 415
    in_1  ======>  (eastbound approach)     |           |  out_1 ======>
    in_0  ======>                           |           |  out_0 ======>
    back_0 <======  (westbound, the other carriageway)

`in_i` feeds `out_i` through traffic light `J`, link `L{i}`. The camera
stands 16 m past the stop line, 10 m up, looking back west along the
approach -- the placement the planner produces.
"""

from __future__ import annotations

import numpy as np
import pytest
from itms_geo.camera import PinholeCamera
from itms_geo.road import Connection, Lane, RoadNetwork
from vision_service.cameras import CameraRig, CameraSpec


def _lane(lane_id: str, edge: str, index: int, x0: float, x1: float, y: float) -> Lane:
    return Lane(lane_id, edge, index, abs(x1 - x0), 3.2, 13.89,
                np.array([[x0, y], [x1, y]]))


def make_network() -> RoadNetwork:
    lanes = {
        "in_0": _lane("in_0", "in", 0, 0.0, 200.0, -4.8),
        "in_1": _lane("in_1", "in", 1, 0.0, 200.0, -1.6),
        "out_0": _lane("out_0", "out", 0, 215.0, 415.0, -4.8),
        "out_1": _lane("out_1", "out", 1, 215.0, 415.0, -1.6),
        "back_0": _lane("back_0", "back", 0, 200.0, 0.0, 1.6),
    }
    edges = {"in": ("in_0", "in_1"), "out": ("out_0", "out_1"), "back": ("back_0",)}
    edge_nodes = {"in": ("W", "J"), "out": ("J", "E"), "back": ("J", "W")}
    junctions = {"J": (207.5, 0.0, "traffic_light"), "W": (0.0, 0.0, "priority"),
                 "E": (415.0, 0.0, "priority")}
    conns = [
        Connection("in_0", "out_0", "J", 0, "s"),
        Connection("in_1", "out_1", "J", 1, "s"),
    ]
    return RoadNetwork(lanes, edges, edge_nodes, junctions, conns)


def make_camera(**kw) -> PinholeCamera:
    base = dict(x=216.0, y=-3.2, height_m=10.0, heading_deg=270.0, pitch_deg=20.0,
                camera_id="camJ")
    base.update(kw)
    return PinholeCamera(**base)


@pytest.fixture
def network() -> RoadNetwork:
    return make_network()


@pytest.fixture
def camera() -> PinholeCamera:
    return make_camera()


@pytest.fixture
def rig(network, camera) -> CameraRig:
    spec = CameraSpec("camJ", camera, tls_id="J", approach_edge="in")
    return CameraRig.build(network, [spec])


@pytest.fixture
def links(network):
    return network.link_lane_maps()
