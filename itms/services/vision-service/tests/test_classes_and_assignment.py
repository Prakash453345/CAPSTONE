"""The class taxonomy agrees with the simulation's PCU table, and the
assignment solver is exact."""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import numpy as np
import pytest
from vision_service.classes import (
    COCO_TO_VCLASS,
    ClassTable,
    VClass,
    vclass_from_name,
    vclass_from_sumo,
)
from vision_service.track.assignment import gated_assignment, iou_matrix, linear_sum_assignment

_ASSIGN_VTYPES = (Path(__file__).resolve().parents[3] / "scenarios" / "demand" / "vijayawada"
                  / "assign_vtypes.py")


def test_pcu_matches_the_simulation_vtypes() -> None:
    """A camera queue_pcu and the SUMO one must mean the same thing, so the
    four simulated classes carry exactly assign_vtypes.py's PCU values."""
    src = _ASSIGN_VTYPES.read_text()
    block = src[src.index("_PCU = {"):src.index("}", src.index("_PCU = {"))]
    pcu = {k: float(v) for k, v in re.findall(r'"(veh_\w+)":\s*([0-9.]+)', block)}
    table = ClassTable.default()
    for vtype, value in pcu.items():
        assert table.pcu(vclass_from_sumo(vtype)) == pytest.approx(value)


@pytest.mark.parametrize("name,expected", [
    ("Auto-Rickshaw", VClass.AUTO_RICKSHAW),
    ("three_wheeler", VClass.AUTO_RICKSHAW),
    ("motorbike", VClass.MOTORCYCLE),
    ("Two-Wheeler", VClass.MOTORCYCLE),
    ("bicycle", VClass.BICYCLE),
    ("minibus", VClass.BUS),
    ("LCV", VClass.TRUCK),
    ("SUV", VClass.CAR),
    ("pedestrian", VClass.PERSON),
    ("traffic light", None),
])
def test_free_text_labels(name, expected) -> None:
    assert vclass_from_name(name) is expected


# BMD-45 and UVH-26 (IISc, Bengaluru Safe City CCTV) label sets, verbatim
_IISC_LABELS = {
    "Hatchback": VClass.CAR, "Sedan": VClass.CAR, "SUV": VClass.CAR, "MUV": VClass.CAR,
    "Van": VClass.CAR, "Bus": VClass.BUS, "Mini-bus": VClass.BUS,
    "Tempo-traveller": VClass.BUS, "Truck": VClass.TRUCK, "LCV": VClass.TRUCK,
    "Three-wheeler": VClass.AUTO_RICKSHAW, "Two-wheeler": VClass.MOTORCYCLE,
    "Bicycle": VClass.BICYCLE, "Other": None,
}


def test_indian_cctv_label_sets_lose_no_vehicle() -> None:
    """Every vehicle label of the Indian CCTV datasets the fine-tune path
    names maps to a class; the first version dropped "MUV" -- an Innova or
    an Ertiga, common on Indian roads -- from every count."""
    got = {name: vclass_from_name(name) for name in _IISC_LABELS}
    assert got == _IISC_LABELS


def test_coco_map_has_no_auto_rickshaw() -> None:
    assert VClass.AUTO_RICKSHAW not in COCO_TO_VCLASS.values()


def test_person_has_no_pcu() -> None:
    assert ClassTable.default().pcu(VClass.PERSON) == 0.0


def test_with_dimensions_overrides_only_what_it_is_given() -> None:
    t = ClassTable.default().with_dimensions({VClass.AUTO_RICKSHAW: (5.0, 1.8)})
    assert t[VClass.AUTO_RICKSHAW].length_m == 5.0
    assert t[VClass.CAR] == ClassTable.default()[VClass.CAR]


def _brute(c: np.ndarray) -> float:
    n, m = c.shape
    if n <= m:
        return min(sum(c[i, p[i]] for i in range(n)) for p in itertools.permutations(range(m), n))
    return min(sum(c[p[j], j] for j in range(m)) for p in itertools.permutations(range(n), m))


@pytest.mark.parametrize("shape", [(1, 1), (3, 3), (2, 5), (5, 2), (4, 4)])
def test_hungarian_is_optimal(shape) -> None:
    rng = np.random.default_rng(sum(shape))
    for _ in range(40):
        c = rng.random(shape)
        r, cc = linear_sum_assignment(c)
        assert len(r) == min(shape)
        assert c[r, cc].sum() == pytest.approx(_brute(c))


def test_gated_assignment_respects_the_gate() -> None:
    c = np.array([[0.1, 0.9], [0.95, 0.2]])
    m, ur, uc = gated_assignment(c, 0.5)
    assert m == [(0, 0), (1, 1)] and ur == [] and uc == []
    m, ur, uc = gated_assignment(np.array([[0.9]]), 0.5)
    assert m == [] and ur == [0] and uc == [0]


def test_gated_assignment_prefers_more_matches() -> None:
    # Greedy would take (0,0) at 0.1 and strand row 1; the optimal answer
    # under the gate matches both rows.
    c = np.array([[0.1, 0.3], [0.2, 0.9]])
    m, _, _ = gated_assignment(c, 0.5)
    assert sorted(m) == [(0, 1), (1, 0)]


def test_iou() -> None:
    a = np.array([[0, 0, 10, 10]])
    b = np.array([[0, 0, 10, 10], [5, 0, 15, 10], [20, 20, 30, 30]])
    np.testing.assert_allclose(iou_matrix(a, b)[0], [1.0, 1 / 3, 0.0])
