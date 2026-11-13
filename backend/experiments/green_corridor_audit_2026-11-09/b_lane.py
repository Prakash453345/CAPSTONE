"""Audit test B (4 EVs, live corridor, district map), with or without the
12 Nov shared-lane phase choice. usage: python b_lane.py <level> <seed> <fix|nofix> <out.json>"""
import sys

import audit_run as A
from audit_lib import dump
from sim_service.routing import RoadGraph

level, seed, mode, out = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
if mode == "nofix":  # the fix is gone entirely
    _orig = RoadGraph.from_network.__func__

    def _no_mates(cls, net_path):
        g = _orig(cls, net_path)
        object.__setattr__(g, "link_lane_mates", {})
        return g

    RoadGraph.from_network = classmethod(_no_mates)
r = A.test_B(level, seed, "full")
r["lane_fix"] = mode
from pathlib import Path
dump(r, Path(out))
print(level, seed, mode, [e.get("travel_s") for e in r["evs"]], r["safety"])
