"""`corridor_geometry`'s math is pure and small enough to hand-check
against a synthetic layout: three junctions on a perfect line should order
trivially and produce exact distances, and a slightly perturbed layout
should still recover the same order (the whole reason this fits a
principal axis instead of just sorting by x or y)."""

from __future__ import annotations

import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# scenarios/ is a collection of scenario-specific scripts, not an installed
# package (see the smoke scripts under scripts/ for the same convention) --
# reached the same way they reach it, by path rather than an import name.
_VIJAYAWADA_DIR = Path(__file__).resolve().parents[5] / "scenarios" / "networks" / "vijayawada"
sys.path.insert(0, str(_VIJAYAWADA_DIR))
import corridor_geometry as cg  # noqa: E402


def _write_net(tmp_path, junctions: dict[str, tuple[float, float]]) -> str:
    root = ET.Element("net")
    for jid, (x, y) in junctions.items():
        ET.SubElement(root, "junction", id=jid, type="traffic_light", x=str(x), y=str(y))
        ET.SubElement(root, "tlLogic", id=jid)
    path = tmp_path / "net.xml"
    ET.ElementTree(root).write(path)
    return str(path)


def test_corridor_order_on_a_straight_line(tmp_path):
    net_path = _write_net(
        tmp_path, {"A": (0.0, 0.0), "B": (100.0, 0.0), "C": (200.0, 0.0)}
    )
    order = cg.corridor_order(net_path)
    assert order in (["A", "B", "C"], ["C", "B", "A"])


def test_cumulative_distances_on_a_straight_line(tmp_path):
    net_path = _write_net(
        tmp_path, {"A": (0.0, 0.0), "B": (100.0, 0.0), "C": (250.0, 0.0)}
    )
    order = cg.corridor_order(net_path)
    distances = cg.cumulative_distances_m(net_path)
    assert distances[order[0]] == 0.0
    # Distances grow monotonically along the order, and the total span
    # (first to last) matches the full 250m regardless of which end the
    # projection called "first".
    assert distances[order[-1]] == 250.0
    assert distances[order[0]] < distances[order[1]] < distances[order[2]]


def test_corridor_order_robust_to_a_slightly_curved_arterial(tmp_path):
    # A gentle curve, not a perfect line -- the dominant-axis fit should
    # still recover the along-corridor order rather than getting confused
    # by the small y-jitter.
    net_path = _write_net(
        tmp_path,
        {
            "A": (0.0, 0.0),
            "B": (100.0, 5.0),
            "C": (200.0, 8.0),
            "D": (300.0, 6.0),
            "E": (400.0, 15.0),
        },
    )
    order = cg.corridor_order(net_path)
    assert order in (["A", "B", "C", "D", "E"], ["E", "D", "C", "B", "A"])


def test_distance_between_consecutive_junctions_is_euclidean(tmp_path):
    net_path = _write_net(tmp_path, {"A": (0.0, 0.0), "B": (3.0, 4.0)})
    distances = cg.cumulative_distances_m(net_path)
    order = cg.corridor_order(net_path)
    span = abs(distances[order[1]] - distances[order[0]])
    assert math.isclose(span, 5.0, rel_tol=1e-9)  # 3-4-5 triangle


def test_single_junction_has_zero_distance(tmp_path):
    net_path = _write_net(tmp_path, {"A": (10.0, 20.0)})
    order = cg.corridor_order(net_path)
    distances = cg.cumulative_distances_m(net_path)
    assert order == ["A"]
    assert distances == {"A": 0.0}
