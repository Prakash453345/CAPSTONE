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
        occupancies={"downstream_0": 0.42},  # TraCI returns a fraction, not a percent
    )
    sampler = QueueStateSampler({"L0": "approach_0"}, {"L0": "downstream_0"}, _PCU_BY_VTYPE)
    _, receiving_occupancy = sampler.sample()
    assert receiving_occupancy == {"L0": 0.42}


def test_receiving_occupancy_is_the_raw_traci_fraction_not_a_percentage(monkeypatch):
    """Regression guard for the 2026-09-18 unit fix. `getLastStepOccupancy`
    already returns the occupied fraction of the lane (measured on this
    corridor: 0.625 on a 599 m lane holding 81 vehicles), so dividing it by
    100 again pinned every occupancy under 0.01 and left `acamp.gate`
    permanently open. This test fails if the division comes back."""
    from sim_service.control.strategies.acamp import AcampConfig, gate

    _fake_traci(
        monkeypatch,
        lane_vehicles={},
        speeds={},
        types={},
        occupancies={"downstream_0": 0.62},
    )
    sampler = QueueStateSampler({"L0": "approach_0"}, {"L0": "downstream_0"}, _PCU_BY_VTYPE)
    _, receiving_occupancy = sampler.sample()
    assert receiving_occupancy["L0"] == 0.62
    # ... and at that occupancy the spillback discount must actually bite.
    # (With the old double division the same lane read 0.0062 and the gate
    # returned 0.99999, i.e. no discount at all.)
    assert gate(receiving_occupancy["L0"], AcampConfig()) < 0.9
    assert gate(0.0062, AcampConfig()) > 0.999


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
        occupancies={"downstream_0": 0.10, "downstream_1": 0.90},
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


def _fake_positions(monkeypatch, lengths: dict[str, float], positions: dict[str, float]):
    monkeypatch.setattr(queue_state_module.traci.lane, "getLength",
                        lambda lane_id: lengths[lane_id])
    monkeypatch.setattr(queue_state_module.traci.vehicle, "getLanePosition",
                        lambda veh_id: positions[veh_id])


def test_a_queue_that_runs_back_past_a_split_in_the_road_is_counted_whole(monkeypatch):
    """A 4 m approach lane (the stretch after a turn bay starts) with the
    rest of the queue on the lane before it: counted on the stop-line lane
    alone it is one vehicle. The lane before feeds two bay lanes, so half
    of its queue is this lane's."""
    _fake_traci(
        monkeypatch,
        lane_vehicles={"bay_1": ["v0"], "road_1": ["v1", "v2", "v3", "v4"]},
        speeds={"v0": 0.0, "v1": 0.0, "v2": 0.0, "v3": 0.0, "v4": 0.0},
        types=dict.fromkeys(["v0", "v1", "v2", "v3", "v4"], "car"),
        occupancies={},
    )
    alone = QueueStateSampler({"L0": "bay_1"}, {}, _PCU_BY_VTYPE)
    chained = QueueStateSampler({"L0": "bay_1"}, {}, _PCU_BY_VTYPE,
                                upstream={"bay_1": [("road_1", 0.5, 4.0)]})
    assert alone.sample()[0] == {"L0": 1.0}
    assert chained.sample()[0] == {"L0": 1.0 + 0.5 * 4}


def test_an_arrival_on_the_lane_before_counts_by_its_distance_to_the_stop_line(monkeypatch):
    _fake_traci(
        monkeypatch,
        lane_vehicles={"bay_1": [], "road_1": ["near", "far"]},
        speeds={"near": 10.0, "far": 10.0},
        types={"near": "car", "far": "car"},
        occupancies={"out_0": 0.0},
    )
    # road_1 is 200 m long; `near` is 30 m before its end (34 m from the stop
    # line: 3.4 s away), `far` 150 m before it (15.4 s, past the 8 s horizon)
    _fake_positions(monkeypatch, {"bay_1": 4.0, "road_1": 200.0},
                    {"near": 170.0, "far": 50.0})
    s = QueueStateSampler({"L0": "bay_1"}, {"L0": "out_0"}, _PCU_BY_VTYPE,
                          upstream={"bay_1": [("road_1", 1.0, 4.0)]})
    assert s.sample_extended().approaching_pcu == {"L0": 1.0}


def test_receiving_occupancy_over_a_split_road_is_what_one_lane_would_read(monkeypatch):
    _fake_traci(
        monkeypatch,
        lane_vehicles={},
        speeds={},
        types={},
        occupancies={"out_0": 1.0, "out_0b": 0.25},
    )
    _fake_positions(monkeypatch, {"out_0": 10.0, "out_0b": 290.0}, {})
    s = QueueStateSampler({"L0": "in_0"}, {"L0": "out_0"}, _PCU_BY_VTYPE,
                          downstream={"out_0": [("out_0b", 1.0, 10.0)]})
    # 10 m full + 290 m a quarter full = 82.5 m of 300
    assert s.sample()[1]["L0"] == 82.5 / 300


def test_a_lane_whose_front_vehicle_stands_behind_a_turner_in_the_box_is_blocked(monkeypatch):
    """Head-of-line blocking (`JunctionContext.blocked_by`): the front
    vehicle is stopped, and a vehicle that left its lane is stopped inside
    the junction just ahead of it. Every movement sharing the lane is
    reported blocked by the waiting vehicle's movement."""
    _fake_traci(
        monkeypatch,
        lane_vehicles={"in_0": ["front", "behind"], "other_0": ["free"], "far_0": ["held"],
                       ":J_2_0": ["turner"], ":J_7_0": ["mover"], ":J_9_0": ["deep"]},
        speeds={"front": 0.0, "behind": 0.0, "free": 0.0, "held": 0.0, "turner": 0.0,
                "mover": 6.0, "deep": 0.0},
        types=dict.fromkeys(["front", "behind", "free", "held"], "car"),
        occupancies={"out_0": 0.0},
    )
    _fake_positions(
        monkeypatch,
        {"in_0": 100.0, "other_0": 100.0, "far_0": 100.0, ":J_2_0": 4.0, ":J_3_0": 14.0,
         ":J_7_0": 14.0, ":J_8_0": 4.0, ":J_9_0": 10.0},
        {"front": 98.0, "behind": 91.0, "free": 99.0, "held": 99.0,
         # a 2.2 m motorcycle at the turn's waiting position, 4 m in: its tail
         # has cleared the stop line, and it is not on the through path
         "turner": 4.0, "mover": 3.0, "deep": 9.0})
    monkeypatch.setattr(queue_state_module.traci.vehicle, "getLength",
                        lambda v: {"turner": 2.2}.get(v, 5.0))
    via = {"in_0": [":J_2_0", ":J_3_0"], "other_0": [":J_7_0"], "far_0": [":J_8_0"],
           ":J_8_0": [":J_9_0"]}
    monkeypatch.setattr(
        queue_state_module.traci.lane, "getLinks",
        lambda lane: [("out_0", True, True, False, v, "G", "s", 10.0) for v in via.get(lane, [])])
    s = QueueStateSampler(
        {"L0": "in_0", "L1": "in_0", "L2": "in_0", "L6": "other_0", "L8": "far_0"},
        {"L0": "out_0"}, _PCU_BY_VTYPE,
        internal_links={":J_2_0": "L2", ":J_3_0": "L1", ":J_7_0": "L7", ":J_8_0": "L8",
                        ":J_9_0": "L8"},
    )
    # in_0: the turner's tail is 1.8 m past the stop line and the front
    # vehicle 2 m short of it -- 3.8 m apart is not "directly behind" ...
    assert s.sample_extended().blocked_by == {}
    # ... a car's length further back in the box, it is (tail 0.5 m past the line)
    monkeypatch.setattr(queue_state_module.traci.vehicle, "getLength",
                        lambda v: {"turner": 3.5}.get(v, 5.0))
    # other_0: the vehicle in the box is moving. far_0: the stopped vehicle is
    # on the second internal lane of its link, 13 m in with its tail at 8 m.
    assert s.sample_extended().blocked_by == {"L0": "L2", "L1": "L2", "L2": "L2"}
    # without the internal-lane map the sampler reports nothing (the default)
    plain = QueueStateSampler({"L0": "in_0"}, {"L0": "out_0"}, _PCU_BY_VTYPE)
    assert plain.sample_extended().blocked_by == {}


def test_the_longest_standing_wait_is_readable_before_a_sample_resets_it(monkeypatch):
    """`ActuationDetector.longest_wait_s`: the wait a link had when it was
    finally served, which `sample` wipes in the same call that serves it."""
    from sim_service.signal_controller import detectors

    occupied = {"in_0": 1, "side_0": 1}
    monkeypatch.setattr(detectors.traci.lane, "getLastStepVehicleNumber",
                        lambda lane: occupied[lane])
    d = detectors.ActuationDetector({"L0": "in_0", "L3": "side_0"})
    assert d.longest_wait_s(0.0) == 0.0
    d.sample(10.0, frozenset({"L0"}))                 # both called at t=10; L0 is green
    d.sample(40.0, frozenset({"L0"}))
    assert d.longest_wait_s(55.0) == 45.0             # L3 has waited since t=10
    _, waits = d.sample(55.0, frozenset({"L3"}))      # ... and is served now: its clock is wiped
    assert waits["L3"] == 0.0
    assert d.longest_wait_s(56.0) == 16.0             # L0 now: last green at t=40
