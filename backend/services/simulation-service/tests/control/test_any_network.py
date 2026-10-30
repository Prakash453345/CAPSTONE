"""The pipeline on road networks other than the Vijayawada corridor:
`itms_domain.scenario` (which network), `scenarios/build_scenario.py` (a
scenario from any network) and `extract_tier0_config` on a traffic light
that controls several junctions (netconvert's --tls.join)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from itms_domain import scenario as scn
from itms_domain.paths import DATA_DIR

_REPO = DATA_DIR
_NETS = _REPO / "scenarios" / "networks" / "vijayawada"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_unset_means_the_vijayawada_corridor(monkeypatch) -> None:
    monkeypatch.delenv(scn.ENV, raising=False)
    s = scn.current()
    assert s.name == "vijayawada" and s.net.exists() and s.cameras.exists()
    assert set(s.levels) == {"light", "medium", "heavy"}
    for cfg, rou in s.levels.values():
        assert cfg.exists() and rou.exists()
    with pytest.raises(ValueError, match="no demand level"):
        s.level("rush")


def test_a_scenario_directory_is_read_from_its_manifest(monkeypatch, tmp_path) -> None:
    (tmp_path / "scenario.json").write_text(json.dumps({
        "name": "elsewhere", "net": "x.net.xml", "cameras_file": "cams.json",
        "levels": {"medium": {"sumocfg": "m.sumocfg", "route": "m.rou.xml"}}}))
    monkeypatch.setenv(scn.ENV, str(tmp_path))
    s = scn.current()
    assert s.name == "elsewhere" and s.directory == tmp_path.resolve()
    assert s.net == tmp_path.resolve() / "x.net.xml"
    assert s.cameras.name == "cams.json"
    assert s.level("medium") == (tmp_path.resolve() / "m.sumocfg", tmp_path.resolve() / "m.rou.xml")


def test_a_light_over_several_junctions_takes_its_conflicts_from_its_own_program() -> None:
    mod = _load(_NETS / "extract_tier0_config.py", "extract_tier0_config_joined")
    root = ET.fromstring("""<net>
        <tlLogic id="joinedS_a_b" type="static" programID="0" offset="0">
            <phase duration="30" state="GGrr"/><phase duration="3" state="yyrr"/>
            <phase duration="30" state="rrGg"/><phase duration="3" state="rryy"/>
        </tlLogic>
        <connection from="e1" to="e2" fromLane="0" toLane="0" tl="joinedS_a_b" linkIndex="0"/>
        <connection from="e1" to="e3" fromLane="1" toLane="0" tl="joinedS_a_b" linkIndex="1"/>
        <connection from="e4" to="e2" fromLane="0" toLane="0" tl="joinedS_a_b" linkIndex="2"/>
        <connection from="e4" to="e5" fromLane="0" toLane="0" tl="joinedS_a_b" linkIndex="3"/>
    </net>""")
    tl = root.find("tlLogic")
    view = mod._joined_view("joinedS_a_b", tl, root)  # noqa: SLF001
    assert sorted(view.get("incLanes").split()) == ["e1_0", "e1_1", "e4_0"]
    cfg = mod._extract_one("joinedS_a_b", tl, view, None, {"e1_0": 13.9})  # noqa: SLF001
    # links green together in a phase are not foes; links never green together are
    assert "L1" not in cfg.conflict_matrix["L0"]
    assert cfg.conflict_matrix["L0"] == frozenset({"L2", "L3"})
    assert cfg.conflict_matrix["L3"] == frozenset({"L0", "L1"})
    assert cfg.ring_order == ("P0", "P1")


def _sumo_home() -> Path:
    if os.environ.get("SUMO_HOME"):
        return Path(os.environ["SUMO_HOME"])
    sumo = pytest.importorskip("sumo")
    return Path(sumo.__file__).parent


def test_a_scenario_is_built_from_a_generated_network(tmp_path) -> None:
    home = _sumo_home()
    if not (home / "bin" / "netgenerate").exists():
        pytest.skip("SUMO binaries not installed")
    out = tmp_path / "g"
    env = {**os.environ, "SUMO_HOME": str(home)}
    subprocess.run([sys.executable, str(_REPO / "scenarios" / "build_scenario.py"),
                    "--generate", "grid:2x2,200,1", "--lefthand", "--levels", "medium:0.5",
                    "--out", str(out), "--no-cameras"], check=True, env=env,
                   capture_output=True, timeout=600)
    m = json.loads((out / "scenario.json").read_text())
    assert m["signalised_junctions"] == 4
    lv = m["levels"]["medium"]
    assert abs(lv["achieved_ds"] - 0.5) <= 0.02 * 0.5 + 1e-9 or len(lv["iterations"]) == 8
    rou = ET.parse(out / lv["route"]).getroot()
    types = {v.get("id") for v in rou.findall("vType")}
    assert {"veh_car", "veh_motorcycle", "veh_auto", "veh_bus"} == types
    assert all(v.get("type") in types for v in rou.findall("vehicle"))
    s = scn.from_directory(out)
    assert s.net.exists() and s.level("medium")[0].exists()


def test_a_change_interval_that_keeps_one_movement_green_is_not_a_phase() -> None:
    """netconvert writes states like `yygrr...` (a turn carries on while the
    rest go yellow) and `yyyrrrGyy`. Counted as phases, they duplicated
    their neighbours' green sets and the cabinet could not read them back."""
    mod = _load(_NETS / "extract_tier0_config.py", "extract_tier0_config_transition")
    root = ET.fromstring("""<net>
        <tlLogic id="j" type="static" programID="0" offset="0">
            <phase duration="42" state="GGgrrrGGG"/><phase duration="3" state="yyyrrrGyy"/>
            <phase duration="42" state="rrrGGGGrr"/><phase duration="3" state="rrryyyGrr"/>
            <phase duration="42" state="GGgrrrGGG"/>
        </tlLogic>
        <junction id="j" type="traffic_light" incLanes="a_0"/>
    </net>""")
    cfg = mod._extract_one("j", root.find("tlLogic"), root.find("junction"), None,  # noqa: SLF001
                           {"a_0": 13.9})
    assert cfg.ring_order == ("P0", "P1")      # the two real greens; the repeat is dropped
    assert cfg.phases["P1"].green_movements == frozenset({"L3", "L4", "L5", "L6"})


def test_a_pedestrian_clearance_inside_a_stage_is_not_a_phase_of_its_own() -> None:
    """OpenStreetMap imports with crossings: each stage is a green with the
    crossings (index 3) green, the same green with them red, then yellow."""
    mod = _load(_NETS / "extract_tier0_config.py", "extract_tier0_config_substage")
    root = ET.fromstring("""<net>
        <tlLogic id="j" type="actuated" programID="0" offset="0">
            <phase duration="10" state="GGrG"/><phase duration="5" state="GGrr"/>
            <phase duration="3" state="yyrr"/>
            <phase duration="10" state="rrGr"/><phase duration="3" state="rryr"/>
        </tlLogic>
        <junction id="j" type="traffic_light" incLanes="a_0"/>
    </net>""")
    assert mod._sub_stage_indices([p.get("state") for p in root.iter("phase")]) == {1}  # noqa: SLF001
    cfg = mod._extract_one("j", root.find("tlLogic"), root.find("junction"), None,  # noqa: SLF001
                           {"a_0": 13.9})
    assert cfg.ring_order == ("P0", "P1")
    assert cfg.phases["P0"].green_movements == frozenset({"L0", "L1", "L3"})
    # a phase that protects what the bigger one only permits is a stage of its own
    assert mod._sub_stage_indices(["GGg", "rrG", "yyy"]) == set()  # noqa: SLF001


def test_a_city_without_signal_tags_gets_lights_where_real_roads_cross(tmp_path) -> None:
    """`city_from_osm.junctions_to_signal`: three or more entering roads of
    the class or above; residential streets meeting stay give-way."""
    sys.path.insert(0, str(_REPO / "scenarios" / "networks" / "vijayawada"))
    mod = _load(_REPO / "scenarios" / "city_from_osm.py", "city_from_osm_rule")
    edges = [  # (id, from, to, type)
        ("a", "W", "X", "highway.secondary"), ("b", "E", "X", "highway.secondary"),
        ("c", "N", "X", "highway.tertiary_link"), ("d", "X", "S", "highway.residential"),
        ("e", "P", "Y", "highway.residential"), ("f", "Q", "Y", "highway.residential"),
        ("g", "R", "Y", "highway.primary"), ("h", "Y", "X", "highway.residential"),
    ]
    xml = "<net>" + "".join(
        f'<edge id="{i}" from="{a}" to="{b}" type="{t}"><lane id="{i}_0" index="0" '
        f'length="50" speed="13.9" shape="0,0 50,0"/></edge>' for i, a, b, t in edges)
    xml += "".join(f'<junction id="{j}" type="priority"/>' for j in "WXENSPQRY") + "</net>"
    net = tmp_path / "n.net.xml"
    net.write_text(xml)
    assert mod.junctions_to_signal(net) == ["X"]            # 3 of 4 entering are tertiary+
    assert mod.junctions_to_signal(net, min_class="residential") == ["X", "Y"]
    assert mod.junctions_to_signal(net, approaches=4) == []
