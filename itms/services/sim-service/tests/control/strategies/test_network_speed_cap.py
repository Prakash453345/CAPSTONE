"""Unit tests for `cap_speeds.py`, the build step that clamps this corridor's
OSM-inherited 80-100 km/h limits to an urban-arterial design speed.

Loaded by path for the same reason `test_tier0_clearance_intervals.py` does it:
`scenarios/networks/vijayawada/` is a scenario script directory, not a package.
"""

from __future__ import annotations

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_NETWORK_DIR = (
    Path(__file__).resolve().parents[5] / "scenarios" / "networks" / "vijayawada"
)
_CAP = _NETWORK_DIR / "cap_speeds.py"
_NET = _NETWORK_DIR / "vijayawada_corridor.net.xml"


def _module():
    spec = importlib.util.spec_from_file_location("cap_speeds_under_test", _CAP)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_NET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<net>
  <edge id="fast" speed="27.78">
    <lane id="fast_0" speed="27.78"/>
    <lane id="fast_1" speed="22.22"/>
  </edge>
  <edge id="slow">
    <lane id="slow_0" speed="8.33"/>
  </edge>
</net>
"""


def test_only_lanes_above_the_cap_are_changed(tmp_path):
    net = tmp_path / "n.net.xml"
    net.write_text(_NET_XML)
    changed = _module().cap_speeds(net, 13.89)
    assert changed == 2
    speeds = {
        lane.get("id"): float(lane.get("speed"))
        for lane in ET.parse(net).getroot().iter("lane")
    }
    assert speeds == {"fast_0": 13.89, "fast_1": 13.89, "slow_0": 8.33}


def test_capping_is_idempotent(tmp_path):
    net = tmp_path / "n.net.xml"
    net.write_text(_NET_XML)
    mod = _module()
    mod.cap_speeds(net, 13.89)
    assert mod.cap_speeds(net, 13.89) == 0


def test_the_committed_corridor_is_already_capped():
    """The network in the repo must stay capped: an uncapped rebuild would
    silently push the kinematic yellow back to its 5 s ceiling and move the
    free-flow reference every delay number is scored against."""
    mod = _module()
    speeds = [
        float(lane.get("speed"))
        for lane in ET.parse(_NET).getroot().iter("lane")
        if lane.get("speed") is not None
    ]
    assert speeds, "the corridor network should declare lane speeds"
    assert max(speeds) <= mod.URBAN_ARTERIAL_MPS + 1e-9
