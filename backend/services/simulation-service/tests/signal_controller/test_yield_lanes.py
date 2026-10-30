"""`yield_lanes_from_net`: the lanes that give way to a signal's exit road."""

from __future__ import annotations

from sim_service.signal_controller.yield_lanes import yield_lanes_from_net

NET = """<net>
 <edge id="in" from="a" to="T"><lane id="in_0" length="100"/></edge>
 <edge id="x" from="T" to="J"><lane id="x_0" length="50"/></edge>
 <edge id="far" from="T" to="J2"><lane id="far_0" length="900"/></edge>
 <edge id="side" from="s" to="J"><lane id="side_0" length="40"/></edge>
 <edge id="out" from="J" to="b"><lane id="out_0" length="40"/></edge>
 <connection from="in" to="x" fromLane="0" toLane="0" tl="T" linkIndex="0" state="o"/>
 <connection from="in" to="far" fromLane="0" toLane="0" tl="T" linkIndex="1" state="o"/>
 <connection from="x" to="out" fromLane="0" toLane="0" state="M"/>
 <connection from="far" to="out" fromLane="0" toLane="0" state="M"/>
 <connection from="side" to="out" fromLane="0" toLane="0" state="m"/>
</net>"""


def test_a_side_road_giving_way_at_the_exit_roads_far_end_is_found(tmp_path):
    p = tmp_path / "n.net.xml"
    p.write_text(NET)
    assert yield_lanes_from_net(p) == {"T": {"L0": ("side_0",)}}


def test_an_exit_road_longer_than_the_limit_is_not_counted(tmp_path):
    p = tmp_path / "n.net.xml"
    p.write_text(NET)
    assert "L1" not in yield_lanes_from_net(p).get("T", {})
    assert yield_lanes_from_net(p, max_exit_m=30.0) == {}
