"""Unit tests for `QueueStateSampler` -- `sample()` calls live TraCI
internally (`traci.lane.getLastStepVehicleIDs`/`getLastStepOccupancy`,
`traci.vehicle.getSpeed`/`getTypeID`), so these monkeypatch those calls to
drive deterministic fleets/occupancies without a real SUMO process, the
same spirit as `test_spillback.py`."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from sim_service.signal_controller import queue_state as queue_state_module
from sim_service.signal_controller.queue_state import QueueStateSampler, load_vtype_pcu

_PCU_BY_VTYPE = {"car": 1.0, "bike": 0.3, "bus": 3.0}


def _fake_traci(monkeypatch, *, lane_vehicles: dict[str, list[str]], speeds: dict[str, float],
                 types: dict[str, str], occupancies: dict[str, float]):
    monkeypatch.setattr(
        queue_state_module.traci.lane,
        "getLastStepVehicleIDs",
        lambda lane_id: tuple(lane_vehicles.get(lane_id, [])),
    )
    monkeypatch.setattr(queue_state_module.traci.vehicle, "getSpeed", lambda veh_id: speeds[veh_id])
    monkeypatch.setattr(queue_state_module.traci.vehicle, "getTypeID", lambda veh_id: types[veh_id])
    monkeypatch.setattr(
        queue_state_module.traci.lane,
        "getLastStepOccupancy",
        lambda lane_id: occupancies[lane_id],
    )


def test_queue_pcu_counts_only_halted_vehicles_weighted_by_pcu(monkeypatch):
    _fake_traci(
        monkeypatch,
        lane_vehicles={"approach_0": ["v1", "v2", "v3"]},
        speeds={"v1": 0.0, "v2": 5.0, "v3": 0.05},  # v2 moving, v1/v3 halted
        types={"v1": "car", "v2": "car", "v3": "bike"},
        occupancies={},
    )
    sampler = QueueStateSampler(
        {"L0": "approach_0"}, {}, _PCU_BY_VTYPE
    )
    queue_pcu, _ = sampler.sample()
    assert queue_pcu == {"L0": 1.0 + 0.3}  # v1 (car, halted) + v3 (bike, halted)


def test_queue_pcu_is_zero_when_lane_is_empty(monkeypatch):
    _fake_traci(monkeypatch, lane_vehicles={}, speeds={}, types={}, occupancies={})
    sampler = QueueStateSampler({"L0": "approach_0"}, {}, _PCU_BY_VTYPE)
    queue_pcu, _ = sampler.sample()
    assert queue_pcu == {"L0": 0.0}


def test_unknown_vtype_defaults_to_pcu_one(monkeypatch):
    _fake_traci(
        monkeypatch,
        lane_vehicles={"approach_0": ["v1"]},
        speeds={"v1": 0.0},
        types={"v1": "some_unmapped_vtype"},
        occupancies={},
    )
    sampler = QueueStateSampler({"L0": "approach_0"}, {}, _PCU_BY_VTYPE)
    queue_pcu, _ = sampler.sample()
    assert queue_pcu == {"L0": 1.0}


def test_halting_speed_boundary_is_strictly_less_than(monkeypatch):
    # Exactly at the threshold does not count as halted -- consistent with
    # camp.py/interlocks.py's own convention of documenting boundary
    # behaviour explicitly rather than leaving it to chance.
    _fake_traci(
        monkeypatch,
        lane_vehicles={"approach_0": ["v1", "v2"]},
        speeds={"v1": 0.1, "v2": 0.099},
        types={"v1": "car", "v2": "car"},
        occupancies={},
    )
    sampler = QueueStateSampler({"L0": "approach_0"}, {}, _PCU_BY_VTYPE)
    queue_pcu, _ = sampler.sample()
    assert queue_pcu == {"L0": 1.0}  # only v2 counts


def test_receiving_occupancy_reads_the_downstream_lane_not_the_approach_lane(monkeypatch):
    _fake_traci(
        monkeypatch,
        lane_vehicles={},
        speeds={},
        types={},
        occupancies={"downstream_0": 42.0},
    )
    sampler = QueueStateSampler({"L0": "approach_0"}, {"L0": "downstream_0"}, _PCU_BY_VTYPE)
    _, receiving_occupancy = sampler.sample()
    assert receiving_occupancy == {"L0": 0.42}


def test_link_with_no_receiving_lane_entry_is_simply_absent(monkeypatch):
    _fake_traci(monkeypatch, lane_vehicles={}, speeds={}, types={}, occupancies={})
    sampler = QueueStateSampler({"L0": "approach_0"}, {}, _PCU_BY_VTYPE)
    _, receiving_occupancy = sampler.sample()
    assert receiving_occupancy == {}


def test_multiple_links_are_independent(monkeypatch):
    _fake_traci(
        monkeypatch,
        lane_vehicles={"approach_0": ["v1"], "approach_1": ["v2"]},
        speeds={"v1": 0.0, "v2": 0.0},
        types={"v1": "car", "v2": "bus"},
        occupancies={"downstream_0": 10.0, "downstream_1": 90.0},
    )
    sampler = QueueStateSampler(
        {"L0": "approach_0", "L1": "approach_1"},
        {"L0": "downstream_0", "L1": "downstream_1"},
        _PCU_BY_VTYPE,
    )
    queue_pcu, receiving_occupancy = sampler.sample()
    assert queue_pcu == {"L0": 1.0, "L1": 3.0}
    assert receiving_occupancy == {"L0": 0.10, "L1": 0.90}


def _route_xml(vtypes: dict[str, float | None]) -> str:
    """Build a minimal route file with one <vType> per entry; a `None`
    value omits the `pcu` param entirely (tests the missing-param default)."""
    parts = ["<routes>"]
    for vtype_id, pcu in vtypes.items():
        if pcu is None:
            parts.append(f'<vType id="{vtype_id}"/>')
        else:
            parts.append(
                f'<vType id="{vtype_id}"><param key="pcu" value="{pcu}"/></vType>'
            )
    parts.append("</routes>")
    return "".join(parts)


def test_load_vtype_pcu_reads_param_values(tmp_path):
    route_path = tmp_path / "r.rou.xml"
    route_path.write_text(_route_xml({"veh_bus": 3.0, "veh_car": 1.0}), encoding="UTF-8")
    assert load_vtype_pcu(route_path) == {"veh_bus": 3.0, "veh_car": 1.0}


def test_load_vtype_pcu_defaults_missing_param_to_one(tmp_path):
    route_path = tmp_path / "r.rou.xml"
    route_path.write_text(_route_xml({"veh_mystery": None}), encoding="UTF-8")
    assert load_vtype_pcu(route_path) == {"veh_mystery": 1.0}


def test_load_vtype_pcu_matches_the_real_corridor_route_file():
    # End-to-end sanity check against the actual checked-in demand file
    # (assign_vtypes.py's own _PCU table), not just synthetic fixtures.
    from pathlib import Path

    root = Path(__file__).resolve().parents[4] / "scenarios" / "demand" / "vijayawada"
    pcu = load_vtype_pcu(root / "vijayawada_corridor.rou.xml")
    assert pcu == {"veh_bus": 3.0, "veh_auto": 0.6, "veh_motorcycle": 0.3, "veh_car": 1.0}


def test_load_vtype_pcu_ignores_vtype_with_no_id(tmp_path):
    route_path = tmp_path / "r.rou.xml"
    root = ET.Element("routes")
    ET.SubElement(root, "vType")  # no id -- must not crash, must be skipped
    good = ET.SubElement(root, "vType", {"id": "veh_car"})
    ET.SubElement(good, "param", {"key": "pcu", "value": "1.0"})
    route_path.write_text(ET.tostring(root, encoding="unicode"), encoding="UTF-8")
    assert load_vtype_pcu(route_path) == {"veh_car": 1.0}
