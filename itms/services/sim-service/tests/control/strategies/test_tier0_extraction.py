"""Tier-0 extraction (`extract_tier0_config.load_configs`) on the two shapes
of netconvert output the corridor never produced but the district does:

* a signal whose `linkIndex` numbering differs from the junction's own
  <request> numbering (seen in a joined cluster): the conflict matrix must
  be translated, or I1 checks the wrong pairs of movements;
* transition phases that keep one movement green ("yyyrrrGyy"): they are
  transitions, not ring phases.

Plus, on both real networks, every signal's conflict matrix checked link by
link against sumolib's own junction-index rule.

Imported by path, like test_tier0_clearance_intervals.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCEN = Path(__file__).resolve().parents[5] / "scenarios" / "networks" / "vijayawada"


def _module():
    spec = importlib.util.spec_from_file_location(
        "extract_tier0_config_extraction_test", _SCEN / "extract_tier0_config.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


x = _module()


def _net(tmp_path: Path, phases: list[str], link_index: dict[tuple[str, int], int]) -> Path:
    """One signalised junction J with two approaches (a: 2 links, b: 1 link).

    Junction link order is a->out1 (0), a->out2 (1), b->out1 (2); a->out1
    and b->out1 conflict (they merge), nothing else does. `link_index` gives
    each connection's signal linkIndex, keyed by (from edge, junction index).
    """
    foes = {0: "100", 1: "000", 2: "001"}  # most-significant-link-first
    conns = [("a", "out1", 0), ("a", "out2", 1), ("b", "out1", 2)]
    xml = ['<net>', '<edge id="a"><lane id="a_0" speed="13.9" length="50"/></edge>',
           '<edge id="b"><lane id="b_0" speed="13.9" length="50"/></edge>',
           '<tlLogic id="J" type="static" programID="0" offset="0">']
    xml += [f'<phase duration="30" state="{s}"/>' for s in phases]
    xml += ['</tlLogic>', '<junction id="J" type="traffic_light" incLanes="a_0 b_0">']
    xml += [f'<request index="{i}" response="000" foes="{foes[i]}" cont="0"/>' for i in range(3)]
    xml += ['</junction>']
    for frm, to, j in conns:
        xml.append(
            f'<connection from="{frm}" to="{to}" fromLane="0" toLane="0" '
            f'tl="J" linkIndex="{link_index[(frm, j)]}"/>'
        )
    xml.append('</net>')
    path = tmp_path / "j.net.xml"
    path.write_text("\n".join(xml))
    return path


def test_identity_numbering_reads_conflicts_directly(tmp_path: Path) -> None:
    net = _net(tmp_path, ["GGr", "yyr", "rrG", "rry"], {("a", 0): 0, ("a", 1): 1, ("b", 2): 2})
    cfg = x.load_configs(net)["J"]
    assert cfg.conflict_matrix == {
        "L0": frozenset({"L2"}), "L1": frozenset(), "L2": frozenset({"L0"})
    }
    assert not cfg.validate()


def test_signal_numbering_that_differs_from_the_junction_is_translated(tmp_path: Path) -> None:
    # the signal numbers b->out1 as link 0, a->out1 as 1, a->out2 as 2 (a
    # rotation, so reading <request index> as the signal's index is wrong)
    net = _net(tmp_path, ["rGG", "ryy", "Grr", "yrr"], {("a", 0): 1, ("a", 1): 2, ("b", 2): 0})
    cfg = x.load_configs(net)["J"]
    # a->out1 (signal L1) conflicts with b->out1 (signal L0), in signal numbering
    assert cfg.conflict_matrix == {
        "L0": frozenset({"L1"}), "L1": frozenset({"L0"}), "L2": frozenset()
    }
    # and the program, which never shows L0 and L2 together, is legal
    for p in cfg.ring_order:
        prot = cfg.phases[p].protected_movements
        assert not any(cfg.conflict_matrix[m] & prot for m in prot)


def test_transition_phases_that_keep_a_movement_green_are_not_ring_phases(tmp_path: Path) -> None:
    # L1 stays green throughout; the "yGr" / "rGy" phases are transitions
    net = _net(tmp_path, ["GGr", "yGr", "rGG", "rGy"], {("a", 0): 0, ("a", 1): 1, ("b", 2): 2})
    cfg = x.load_configs(net)["J"]
    assert cfg.ring_order == ("P0", "P1")
    assert cfg.phases["P0"].green_movements == {"L0", "L1"}
    assert cfg.phases["P1"].green_movements == {"L1", "L2"}


@pytest.mark.parametrize("name", ["vijayawada_corridor", "vijayawada_district"])
def test_real_networks_match_sumolib_link_by_link(name: str) -> None:
    sumolib = pytest.importorskip("sumolib")
    path = _SCEN / f"{name}.net.xml"
    if not path.exists():
        pytest.skip(f"{name} not built")
    cfgs = x.load_configs(path)
    net = sumolib.net.readNet(str(path))
    for tls in net.getTrafficLights():
        conns = {}
        for in_lane, out_lane, li in tls.getConnections():
            for c in in_lane.getOutgoing():
                if c.getToLane() == out_lane and c.getTLLinkIndex() == li:
                    conns[li] = c
        node = next(iter(conns.values())).getJunction()
        cfg = cfgs[tls.getID()]
        for a, ca in conns.items():
            row = node._foes[ca.getJunctionIndex()][::-1]
            want = {f"L{b}" for b, cb in conns.items() if b != a and row[cb.getJunctionIndex()] == "1"}
            assert cfg.conflict_matrix[f"L{a}"] == want, (tls.getID(), a)
        # no ring phase shows two conflicting protected movements (I1), and
        # every ring phase is distinguishable on readback
        greens = [cfg.phases[p].green_movements for p in cfg.ring_order]
        assert len(set(greens)) == len(greens), tls.getID()
        for p in cfg.ring_order:
            prot = cfg.phases[p].protected_movements
            assert not any(cfg.conflict_matrix[m] & prot for m in prot), (tls.getID(), p)
        assert not cfg.validate(), tls.getID()
