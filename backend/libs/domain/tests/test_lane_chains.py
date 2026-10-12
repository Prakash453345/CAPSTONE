"""`itms_domain.lane_chains`: an approach SUMO splits into several edges is
chained back to the road before it, and never onto the road's other
direction."""

from __future__ import annotations

from itms_domain.lane_chains import Link, from_sumo_net, lane_chains, vias_from_sumo_net
from itms_domain.paths import DATA_DIR

_ROOT = DATA_DIR


def _net():
    """U --in1--> P --in2 (two lanes: a turn bay)--> S (signal) --r--> Q --r2--> Z,
    with the other direction S --out2--> P --out1--> U and a U-turn at the
    dead end U."""
    spec = {"in1": ("U", "P", 1, 200.0), "in2": ("P", "S", 2, 30.0),
            "out2": ("S", "P", 1, 30.0), "out1": ("P", "U", 1, 200.0),
            "r": ("S", "Q", 1, 50.0), "r2": ("Q", "Z", 1, 250.0)}
    lanes = {f"{e}_{i}": (e, length) for e, (_, _, n, length) in spec.items() for i in range(n)}
    edge_nodes = {e: (a, b) for e, (a, b, _, _) in spec.items()}
    types = {"U": "dead_end", "P": "priority", "S": "traffic_light", "Q": "priority",
             "Z": "dead_end"}
    links = [Link("in1_0", "in2_0", direction="s"), Link("in1_0", "in2_1", direction="s"),
             Link("in2_0", "r_0", "S", 0, "s"), Link("in2_1", "r_0", "S", 1, "s"),
             Link("r_0", "r2_0", direction="s"), Link("out2_0", "out1_0", direction="s"),
             # the same road's other direction: never part of a chain, whether
             # or not SUMO marks the turn as a U-turn
             Link("out1_0", "in1_0", direction="t"), Link("out2_0", "in2_0", direction="l")]
    return lanes, edge_nodes, types, links


def test_an_approach_split_by_a_turn_bay_is_chained_back_to_the_road_before_it() -> None:
    up, down = lane_chains(*_net())
    # in1_0 feeds both bay lanes, so each gets half of it; it ends 30 m (in2's
    # length) before the stop line; the walk stops at the dead end U
    assert up == {"in2_0": [("in1_0", 0.5, 30.0)], "in2_1": [("in1_0", 0.5, 30.0)]}
    assert down == {"r_0": [("r2_0", 1.0, 50.0)]}


def test_a_chain_stops_at_its_length_cap_and_at_a_real_junction() -> None:
    lanes, edge_nodes, types, links = _net()
    assert lane_chains(lanes, edge_nodes, types, links, max_m=20.0) == ({}, {})
    edge_nodes["side"] = ("P", "W")          # a third road meets at P
    assert lane_chains(lanes, edge_nodes, types, links)[0] == {}
    types["Q"] = "traffic_light"             # a signal ends a chain
    assert lane_chains(lanes, edge_nodes, types, links)[1] == {}


def test_the_vijayawada_corridor_has_one_split_receiving_lane_and_no_split_approach() -> None:
    up, down = from_sumo_net(_ROOT / "scenarios" / "networks" / "vijayawada"
                             / "vijayawada_corridor.net.xml")
    assert up == {}
    assert list(down) == ["848411146_2"] and down["848411146_2"][0][0] == "470154178_0"


def test_the_internal_lanes_inside_a_split_approach_are_found(tmp_path) -> None:
    """`vias_from_sumo_net`: the piece of road between `in1` and the turn bay
    `in2` is an internal lane of node P -- where the first queued vehicle
    stands when the bay is shorter than a vehicle. The internal lanes of the
    signal itself (after the stop line) are not part of the approach."""
    net = tmp_path / "n.net.xml"
    net.write_text("""<net>
      <connection from="in1" to="in2" fromLane="0" toLane="0" via=":P_0_0" dir="s"/>
      <connection from="in1" to="in2" fromLane="0" toLane="1" via=":P_0_1" dir="s"/>
      <connection from="in2" to="r" fromLane="0" toLane="0" via=":S_0_0" tl="S" dir="s"/>
      <connection from="in2" to="r" fromLane="1" toLane="0" via=":S_1_0" tl="S" dir="s"/>
      <connection from=":P_0" to="in2" fromLane="0" toLane="0" dir="s"/>
    </net>""")
    upstream = {"in2_0": [("in1_0", 0.5, 30.0)], "in2_1": [("in1_0", 0.5, 30.0)]}
    assert vias_from_sumo_net(net, upstream) == {"in2_0": [(":P_0_0", 1.0)],
                                                 "in2_1": [(":P_0_1", 1.0)]}
    assert vias_from_sumo_net(net, {}) == {}


def test_a_network_with_no_split_approach_has_no_vias() -> None:
    assert vias_from_sumo_net(_ROOT / "scenarios" / "networks" / "vijayawada"
                              / "vijayawada_corridor.net.xml") == {}


def test_a_stop_line_lane_too_short_for_a_vehicle_is_watched_with_what_leads_into_it(tmp_path):
    """`short_m`: junction P sits 0.2 m before the signal S, so the approach
    lane `stub_0` cannot hold a vehicle's front and, P being a real junction,
    is not chained. The lanes inside P that lead into it are where its queue
    stands. A long approach (`long_0`) is left alone."""
    net = tmp_path / "n.net.xml"
    net.write_text("""<net>
      <edge id="a"><lane id="a_0" length="200.0"/></edge>
      <edge id="side"><lane id="side_0" length="80.0"/></edge>
      <edge id="stub"><lane id="stub_0" length="0.2"/></edge>
      <edge id="long"><lane id="long_0" length="150.0"/></edge>
      <edge id="out"><lane id="out_0" length="100.0"/></edge>
      <connection from="a" to="stub" fromLane="0" toLane="0" via=":P_0_0" dir="s"/>
      <connection from="side" to="stub" fromLane="0" toLane="0" via=":P_1_0" dir="r"/>
      <connection from="side" to="long" fromLane="0" toLane="0" via=":P_2_0" dir="l"/>
      <connection from="stub" to="out" fromLane="0" toLane="0" via=":S_0_0" tl="S" dir="s"/>
      <connection from="long" to="out" fromLane="0" toLane="0" via=":S_1_0" tl="S" dir="s"/>
    </net>""")
    assert vias_from_sumo_net(net, {}) == {}
    assert vias_from_sumo_net(net, {}, short_m=5.0) == {"stub_0": [(":P_0_0", 1.0),
                                                               (":P_1_0", 1.0)]}
