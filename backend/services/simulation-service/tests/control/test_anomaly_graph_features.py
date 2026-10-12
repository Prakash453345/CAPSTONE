"""`AnomalyGraph` / `LinkFeatureSampler` / `FeatureNormalizer`.

The graph test parses the real corridor `.net.xml` (XML only, no SUMO). The
sampler test builds a 2-node graph by hand and monkeypatches the TraCI lane/
vehicle calls, the same approach as `test_queue_state.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from itms_domain.paths import DATA_DIR
from sim_service.control.anomaly import graph_features as gf
from sim_service.control.anomaly.graph_features import (
    FEATURE_NAMES,
    N_FEATURES,
    AnomalyGraph,
    FeatureNormalizer,
    LinkFeatureSampler,
)

_NET = (
    DATA_DIR
    / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
)


# ---- AnomalyGraph.from_network -----------------------------------------


def test_graph_has_one_node_per_controlled_link_in_stable_order():
    g = AnomalyGraph.from_network(_NET)
    assert g.num_nodes == 73  # 7 signal-controlled junctions on this corridor
    # node order is deterministic: junctions sorted, links numeric within
    assert g.node_ids == AnomalyGraph.from_network(_NET).node_ids
    # every node id round-trips through index_of
    for i, node_id in enumerate(g.node_ids):
        tls, link = node_id.split("::")
        assert g.index_of(tls, link) == i
        assert g.tls_of[i] == tls and g.link_of[i] == link


def test_links_sort_numerically_not_lexically():
    g = AnomalyGraph.from_network(_NET)
    for tls in set(g.tls_of):
        links = [g.link_of[i] for i in range(g.num_nodes) if g.tls_of[i] == tls]
        nums = [int(x[1:]) for x in links]
        assert nums == sorted(nums)  # L2 before L10


def test_downstream_edges_match_receiving_lane_topology():
    g = AnomalyGraph.from_network(_NET, intra_junction_edges=False, self_loops=False)
    assert all(t == "downstream" for t in g.edge_type)
    assert g.num_edges == 71  # measured directly from link_to_receiving_lane_map
    # every downstream edge connects a node whose receiving lane is the
    # destination node's approach lane
    for (src, dst), etype in zip(g.edge_index, g.edge_type, strict=True):
        assert etype == "downstream"
        assert g.receiving_lane_of[src] == g.approach_lane_of[dst]


def test_intra_and_self_edges_are_added_by_default():
    g = AnomalyGraph.from_network(_NET)
    types = set(g.edge_type)
    assert types == {"downstream", "intra", "self"}
    assert g.edge_type.count("self") == g.num_nodes
    # intra edges never cross junctions
    for (src, dst), etype in zip(g.edge_index, g.edge_type, strict=True):
        if etype == "intra":
            assert g.tls_of[src] == g.tls_of[dst] and src != dst


def test_adjacency_lists_include_self_and_are_deduped():
    g = AnomalyGraph.from_network(_NET)
    adj = g.adjacency_lists()
    assert len(adj) == g.num_nodes
    for dst, srcs in enumerate(adj):
        assert dst in srcs  # self loop
        assert srcs == sorted(set(srcs))


# ---- LinkFeatureSampler ----------------------------------------------


def _mini_graph() -> AnomalyGraph:
    # node 0: J1/L0 approach lane "a_0", discharges into "b_0"
    # node 1: J1/L1 approach lane "b_0" (fed by node 0)
    return AnomalyGraph(
        node_ids=("J1::L0", "J1::L1"),
        tls_of=("J1", "J1"),
        link_of=("L0", "L1"),
        approach_lane_of=("a_0", "b_0"),
        receiving_lane_of=("b_0", None),
        edge_index=((0, 1), (0, 0), (1, 1)),
        edge_type=("downstream", "self", "self"),
    )


@pytest.fixture
def patched_traci(monkeypatch):
    state = SimpleNamespace(
        lane_vehicles={}, speeds={}, types={}, positions={},
        occupancy={}, length={}, max_speed={}, halting={}, mean_speed={},
    )
    t = gf.traci
    monkeypatch.setattr(t.lane, "getLastStepVehicleIDs",
                        lambda ln: tuple(state.lane_vehicles.get(ln, [])))
    monkeypatch.setattr(t.vehicle, "getSpeed", lambda v: state.speeds[v])
    monkeypatch.setattr(t.vehicle, "getTypeID", lambda v: state.types.get(v, "car"))
    monkeypatch.setattr(t.vehicle, "getLanePosition", lambda v: state.positions.get(v, 0.0))
    monkeypatch.setattr(t.lane, "getLastStepOccupancy", lambda ln: state.occupancy.get(ln, 0.0))
    monkeypatch.setattr(t.lane, "getLength", lambda ln: state.length.get(ln, 140.0))
    monkeypatch.setattr(t.lane, "getMaxSpeed", lambda ln: state.max_speed.get(ln, 14.0))
    monkeypatch.setattr(t.lane, "getLastStepHaltingNumber", lambda ln: state.halting.get(ln, 0))
    monkeypatch.setattr(t.lane, "getLastStepMeanSpeed",
                        lambda ln: state.mean_speed.get(ln, state.max_speed.get(ln, 14.0)))
    return state


def _cfg(green_link: str) -> SimpleNamespace:
    phase = SimpleNamespace(green_movements=frozenset({green_link}))
    return SimpleNamespace(phases={"P0": phase}, max_green_s={"P0": 50.0})


def test_sample_returns_one_row_per_node_with_full_feature_width(patched_traci):
    s = LinkFeatureSampler(_mini_graph(), {"J1": _cfg("L0")}, {"car": 1.0})
    rows = s.sample(0.0, {"J1": ("P0", 10.0)})
    assert len(rows) == 2
    assert all(len(r) == N_FEATURES for r in rows)
    assert N_FEATURES == len(FEATURE_NAMES)


def test_empty_lane_reads_as_free_flowing_and_unqueued(patched_traci):
    s = LinkFeatureSampler(_mini_graph(), {"J1": _cfg("L0")}, {"car": 1.0})
    rows = s.sample(0.0, {"J1": ("P0", 0.0)})
    row0 = dict(zip(FEATURE_NAMES, rows[0], strict=True))
    assert row0["queue_pcu"] == 0.0
    assert row0["halting_frac"] == 0.0
    assert row0["mean_speed_frac"] == pytest.approx(1.0)  # SUMO returns max speed when empty


def test_is_green_follows_phase_membership(patched_traci):
    s = LinkFeatureSampler(_mini_graph(), {"J1": _cfg("L0")}, {"car": 1.0})
    rows = s.sample(0.0, {"J1": ("P0", 25.0)})
    g0 = dict(zip(FEATURE_NAMES, rows[0], strict=True))
    g1 = dict(zip(FEATURE_NAMES, rows[1], strict=True))
    assert g0["is_green"] == 1.0   # L0 is in P0's green movements
    assert g1["is_green"] == 0.0   # L1 is not
    assert g0["phase_age_frac"] == pytest.approx(25.0 / 50.0)


def test_a_queue_on_a_red_approach_shows_up_in_queue_and_speed_features(patched_traci):
    patched_traci.lane_vehicles["a_0"] = ["v1", "v2", "v3"]
    patched_traci.speeds.update({"v1": 0.0, "v2": 0.0, "v3": 6.0})
    patched_traci.halting["a_0"] = 2
    patched_traci.mean_speed["a_0"] = 2.0
    patched_traci.length["a_0"] = 70.0
    s = LinkFeatureSampler(_mini_graph(), {"J1": _cfg("L1")}, {"car": 1.0})  # L0 is red
    rows = s.sample(0.0, {"J1": ("P0", 5.0)})
    r0 = dict(zip(FEATURE_NAMES, rows[0], strict=True))
    assert r0["queue_pcu"] == pytest.approx(2.0)          # v1 + v2 halted, car pcu 1.0
    assert r0["halting_frac"] == pytest.approx(2.0 / (70.0 / 7.0))
    assert r0["mean_speed_frac"] == pytest.approx(2.0 / 14.0)
    assert r0["is_green"] == 0.0


def test_time_of_day_sinusoids_track_sim_time(patched_traci):
    s = LinkFeatureSampler(_mini_graph(), {"J1": _cfg("L0")}, {"car": 1.0},
                           demand_period_s=3600.0)
    at0 = s.sample(0.0, {"J1": ("P0", 0.0)})[0]
    quarter = s.sample(900.0, {"J1": ("P0", 0.0)})[0]
    d0 = dict(zip(FEATURE_NAMES, at0, strict=True))
    dq = dict(zip(FEATURE_NAMES, quarter, strict=True))
    assert d0["sin_tod"] == pytest.approx(0.0, abs=1e-9)
    assert d0["cos_tod"] == pytest.approx(1.0, abs=1e-9)
    assert dq["sin_tod"] == pytest.approx(1.0, abs=1e-9)   # quarter period
    assert dq["cos_tod"] == pytest.approx(0.0, abs=1e-9)


def test_missing_junction_phase_is_treated_as_all_red(patched_traci):
    s = LinkFeatureSampler(_mini_graph(), {"J1": _cfg("L0")}, {"car": 1.0})
    rows = s.sample(0.0, {})  # no phase info for J1 at all
    for r in rows:
        d = dict(zip(FEATURE_NAMES, r, strict=True))
        assert d["is_green"] == 0.0
        assert d["phase_age_frac"] == 0.0


# ---- FeatureNormalizer ---------------------------------------------


def _frame(val: float) -> list[list[float]]:
    return [[val] * N_FEATURES, [val * 2] * N_FEATURES]


def test_normalizer_standardizes_non_passthrough_features():
    frames = [_frame(1.0), _frame(3.0)]  # values 1,2,3,6 per feature
    norm = FeatureNormalizer.fit(frames)
    out = norm.transform_row([norm.mean[f] for f in range(N_FEATURES)])
    for f, name in enumerate(FEATURE_NAMES):
        if name in norm.passthrough:
            assert out[f] == norm.mean[f]
        else:
            assert out[f] == pytest.approx(0.0)  # mean maps to 0


def test_normalizer_passthrough_columns_are_identity():
    norm = FeatureNormalizer.fit([_frame(5.0)])
    row = list(range(N_FEATURES))
    out = norm.transform_row(row)
    for f, name in enumerate(FEATURE_NAMES):
        if name in norm.passthrough:
            assert out[f] == row[f]


def test_normalizer_roundtrips_through_json(tmp_path):
    norm = FeatureNormalizer.fit([_frame(2.0), _frame(7.0)])
    p = tmp_path / "norm.json"
    norm.save(p)
    back = FeatureNormalizer.load(p)
    assert back.mean == norm.mean
    assert back.std == norm.std
    assert back.passthrough == norm.passthrough


def test_normalizer_rejects_a_feature_name_mismatch(tmp_path, monkeypatch):
    norm = FeatureNormalizer.fit([_frame(1.0)])
    p = tmp_path / "norm.json"
    norm.save(p)
    import json

    payload = json.loads(p.read_text())
    payload["feature_names"] = ["something_else"]
    p.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        FeatureNormalizer.load(p)


def test_normalizer_fit_rejects_empty_input():
    with pytest.raises(ValueError):
        FeatureNormalizer.fit([])
