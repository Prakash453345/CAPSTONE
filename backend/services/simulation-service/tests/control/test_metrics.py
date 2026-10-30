"""Unit tests for the M3 metrics collector. `parse_tripinfo` and
`load_vtype_occupancy` are tested against small hand-written XML fixtures
(not a real SUMO output) so each field mapping is directly checkable;
`score_trips`'s aggregation math is tested against hand-computed
expected numbers, the same "small enough to verify by hand" spirit as
`test_webster_timing.py`."""

from __future__ import annotations

import math

from sim_service.control import metrics


def _trip(
    vehicle_id: str,
    vtype: str,
    *,
    depart_s: float,
    time_loss_s: float = 0.0,
    waiting_time_s: float = 0.0,
    waiting_count: int = 0,
    duration_s: float = 1.0,
) -> metrics.TripRecord:
    return metrics.TripRecord(
        vehicle_id, vtype, depart_s, duration_s, time_loss_s, waiting_time_s, waiting_count
    )


def _write(tmp_path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content)
    return str(path)


def _tripinfo_xml(rows: list[dict]) -> str:
    body = "\n".join(
        (
            f'<tripinfo id="{r["id"]}" vType="{r["vtype"]}" depart="{r["depart"]}" '
            f'duration="{r.get("duration", 0)}" timeLoss="{r.get("time_loss", 0)}" '
            f'waitingTime="{r.get("waiting_time", 0)}" '
            f'waitingCount="{r.get("waiting_count", 0)}"/>'
        )
        for r in rows
    )
    return f"<tripinfos>{body}</tripinfos>"


def _route_xml(vtypes: dict[str, float | None]) -> str:
    body = "\n".join(
        f'<vType id="{vid}">'
        + (f'<param key="occupancy" value="{occ}"/>' if occ is not None else "")
        + "</vType>"
        for vid, occ in vtypes.items()
    )
    return f"<routes>{body}</routes>"


def test_parse_tripinfo_reads_every_field(tmp_path):
    path = _write(
        tmp_path,
        "trips.xml",
        _tripinfo_xml(
            [
                {
                    "id": "veh0",
                    "vtype": "veh_bus",
                    "depart": "10.5",
                    "duration": "120.0",
                    "time_loss": "30.0",
                    "waiting_time": "15.0",
                    "waiting_count": "3",
                }
            ]
        ),
    )
    [record] = metrics.parse_tripinfo(path)
    assert record.vehicle_id == "veh0"
    assert record.vtype == "veh_bus"
    assert record.depart_s == 10.5
    assert record.duration_s == 120.0
    assert record.time_loss_s == 30.0
    assert record.waiting_time_s == 15.0
    assert record.waiting_count == 3


def test_load_vtype_occupancy_reads_param_and_defaults_missing_to_one(tmp_path):
    path = _write(
        tmp_path,
        "routes.xml",
        _route_xml({"veh_bus": 40.0, "veh_car": 1.5, "veh_passenger": None}),
    )
    occupancy = metrics.load_vtype_occupancy(path)
    assert occupancy == {"veh_bus": 40.0, "veh_car": 1.5, "veh_passenger": 1.0}


def test_score_trips_excludes_departures_before_warmup():
    trips = [
        _trip("v0", "veh_car", depart_s=100.0, time_loss_s=999, waiting_time_s=999,
              waiting_count=99),
        _trip("v1", "veh_car", depart_s=700.0, time_loss_s=10.0, waiting_time_s=5.0,
              waiting_count=1),
    ]
    result = metrics.score_trips(
        trips, {"veh_car": 1.0}, warmup_s=600.0
    )
    assert result.n_trips_total == 2
    assert result.n_trips_scored == 1
    assert result.person_delay_s == 10.0
    assert result.wait_time_s.mean_s == 5.0
    assert result.stops_per_vehicle == 1.0


def test_score_trips_person_delay_is_occupancy_weighted():
    # A bus carrying 40 with 10s of timeLoss delays 400 person-seconds --
    # far more than a car with the same timeLoss, which is the whole point
    # of person-delay over plain vehicle-delay (build guide §8.1).
    trips = [
        _trip("bus0", "veh_bus", depart_s=700.0, time_loss_s=10.0),
        _trip("car0", "veh_car", depart_s=700.0, time_loss_s=10.0),
    ]
    occupancy = {"veh_bus": 40.0, "veh_car": 1.5}
    result = metrics.score_trips(trips, occupancy, warmup_s=0.0)
    assert math.isclose(result.person_delay_s, 40.0 * 10.0 + 1.5 * 10.0)


def test_score_trips_throughput_is_measured_over_the_scored_window():
    # Fixed 2026-09-18: throughput used to divide by a hard-coded nominal
    # duration no caller overrode, which made it identical for every
    # controller. It is now persons cleared after warm-up, over the window
    # those trips actually occupy.
    trips = [
        _trip("v0", "veh_bus", depart_s=100.0),                      # pre-warmup: excluded
        _trip("v1", "veh_car", depart_s=700.0, duration_s=100.0),
        _trip("v2", "veh_car", depart_s=1000.0, duration_s=2600.0),  # last arrival 3600 s
    ]
    occupancy = {"veh_bus": 40.0, "veh_car": 1.5}
    result = metrics.score_trips(trips, occupancy, warmup_s=600.0)
    # 3.0 persons over (3600 - 600) s = 3.6 persons/hour.
    assert math.isclose(result.person_throughput_per_hour, 3.6)


def test_score_trips_scores_the_scheduled_departure_not_the_insertion_time():
    # Fixed 2026-09-18: congestion delays SUMO's insertion, so filtering on
    # the recorded departure scored a different population per arm.
    trips = [
        _trip("v0", "veh_car", depart_s=650.0, time_loss_s=10.0),  # scheduled at 500 -> out
        _trip("v1", "veh_car", depart_s=700.0, time_loss_s=20.0),  # scheduled at 610 -> in
    ]
    result = metrics.score_trips(
        trips, {"veh_car": 1.0}, warmup_s=600.0,
        scheduled_depart_s={"v0": 500.0, "v1": 610.0},
    )
    assert result.n_trips_scored == 1
    assert math.isclose(result.person_delay_s, 20.0)


def test_score_trips_missing_vtype_defaults_to_occupancy_one():
    trips = [_trip("v0", "unknown_vtype", depart_s=700.0, time_loss_s=8.0)]
    result = metrics.score_trips(trips, {}, warmup_s=0.0)
    assert result.person_delay_s == 8.0


def test_wait_time_distribution_reports_percentiles_not_just_mean():
    # 100 trips, waiting times 1..100 -- p99 and max should differ sharply
    # from the mean, which is exactly why the gate wants a distribution.
    trips = [
        _trip(f"v{i}", "veh_car", depart_s=700.0, waiting_time_s=float(i))
        for i in range(1, 101)
    ]
    result = metrics.score_trips(trips, {"veh_car": 1.0}, warmup_s=0.0)
    assert math.isclose(result.wait_time_s.mean_s, 50.5, rel_tol=1e-9)
    assert result.wait_time_s.max_s == 100.0
    assert result.wait_time_s.p99_s > result.wait_time_s.p50_s
    assert result.wait_time_s.p95_s > result.wait_time_s.p50_s


def test_score_trips_on_empty_input_is_all_zero():
    result = metrics.score_trips([], {}, warmup_s=600.0)
    assert result.n_trips_total == 0
    assert result.n_trips_scored == 0
    assert result.person_delay_s == 0.0
    assert result.stops_per_vehicle == 0.0
    assert result.wait_time_s.max_s == 0.0


def test_compute_run_metrics_end_to_end_from_files(tmp_path):
    tripinfo_path = _write(
        tmp_path,
        "trips.xml",
        _tripinfo_xml(
            [
                {"id": "v0", "vtype": "veh_bus", "depart": "700",
                 "time_loss": "20", "waiting_time": "10", "waiting_count": "2"},
                {"id": "v1", "vtype": "veh_car", "depart": "700",
                 "time_loss": "5", "waiting_time": "2", "waiting_count": "1"},
            ]
        ),
    )
    route_path = _write(tmp_path, "routes.xml", _route_xml({"veh_bus": 40.0, "veh_car": 1.5}))
    result = metrics.compute_run_metrics(
        tripinfo_path, route_path, warmup_s=600.0
    )
    assert result.n_trips_scored == 2
    assert math.isclose(result.person_delay_s, 40.0 * 20.0 + 1.5 * 5.0)
