"""`itms_domain.phase_layout.paired_layout`: a split-phased four-way junction
(one phase per approach) becomes two phases of facing approaches, the turn that
crosses the oncoming stream running permissive; with `turn_phases`, each pair
also gets a protected-turn phase. Anything it cannot pair safely is left as it
was."""

from __future__ import annotations

from itms_domain.phase_layout import paired_layout
from itms_domain.signal import Phase, Tier0Config

# Left-hand traffic. Approaches N (heading 270: travelling south), S (90),
# E (180), W (0). Each has a left turn (free), a straight, a right turn
# (crosses the oncoming straight).
_APPROACH = {"N": 270.0, "S": 90.0, "E": 180.0, "W": 0.0}
_LINKS = {}
for k, a in enumerate("NSEW"):
    for j, d in enumerate("lsr"):
        _LINKS[f"L{3 * k + j}"] = (a, d)


def _cfg(conflicts: dict[str, set[str]]) -> Tier0Config:
    phases = {f"P{k}": Phase(f"P{k}", frozenset({f"L{3 * k}", f"L{3 * k + 1}", f"L{3 * k + 2}"}))
              for k in range(4)}
    sym: dict[str, set[str]] = {m: set() for m in _LINKS}
    for a, bs in conflicts.items():
        for b in bs:
            sym[a].add(b)
            sym[b].add(a)
    return Tier0Config(intersection_id="J", phases=phases, ring_order=tuple(phases),
                       conflict_matrix={m: frozenset(c) for m, c in sym.items()},
                       min_green_s=dict.fromkeys(phases, 7.0),
                       max_green_s=dict.fromkeys(phases, 40.0), yellow_s=3.0, all_red_s=2.0)


# N straight L1 / S straight L4 cross nothing of each other; each right turn
# crosses the other's straight; every N/S movement crosses every E/W straight.
_CONFLICTS = {"L2": {"L4"}, "L5": {"L1"}, "L8": {"L10"}, "L11": {"L7"}}
for ns in ("L0", "L1", "L2", "L3", "L4", "L5"):
    _CONFLICTS.setdefault(ns, set()).update({"L7", "L10"})


def test_facing_approaches_share_a_phase_and_the_crossing_turn_yields() -> None:
    out = paired_layout(_cfg(_CONFLICTS), _LINKS, _APPROACH, lefthand=True)
    assert len(out.ring_order) == 2
    ns, ew = sorted(out.phases.values(), key=lambda p: "L1" not in p.green_movements)
    assert ns.green_movements == frozenset({"L0", "L1", "L2", "L3", "L4", "L5"})
    assert ns.protected_movements == frozenset({"L0", "L1", "L3", "L4"})
    assert ew.protected_movements == frozenset({"L6", "L7", "L9", "L10"})
    assert out.validate() == []


def test_turn_phases_run_the_crossing_turns_protected() -> None:
    out = paired_layout(_cfg(_CONFLICTS), _LINKS, _APPROACH, lefthand=True, turn_phases=True)
    assert len(out.ring_order) == 4 and all(p in out.phases for p in ("G0t", "G1t"))
    # both N/S right turns, plus the free lefts, which cross neither
    ns_turns = next(p for p in out.phases.values() if "L2" in p.protected_movements)
    assert ns_turns.green_movements == frozenset({"L2", "L5", "L0", "L3"})


def test_two_straight_streams_that_cross_leave_the_junction_alone() -> None:
    bad = {**_CONFLICTS, "L1": _CONFLICTS["L1"] | {"L4"}}
    cfg = _cfg(bad)
    assert paired_layout(cfg, _LINKS, _APPROACH, lefthand=True) is cfg


def test_a_junction_that_is_not_split_phased_is_left_alone() -> None:
    cfg = _cfg(_CONFLICTS)
    merged = Phase("P0", frozenset({"L0", "L1", "L2", "L3", "L4", "L5"}),
                   protected_movements=frozenset({"L0", "L1", "L3", "L4"}))
    cfg2 = Tier0Config(**{**cfg.__dict__, "phases": {**cfg.phases, "P0": merged}})
    assert paired_layout(cfg2, _LINKS, _APPROACH, lefthand=True) is cfg2


def test_the_split_phased_arterial_is_paired_with_right_turns_giving_way() -> None:
    """On arterial_lh (left-hand traffic, one phase per approach) the junction
    C0 becomes two phases; the right turns, which cross the oncoming stream,
    are the only permissive movements."""
    from pathlib import Path

    import pytest
    from itms_domain.phase_layout import net_links

    net = Path(__file__).resolve().parents[3] / "scenarios" / "generated" / "arterial_lh" / \
        "arterial_lh.net.xml"
    if not net.exists():
        pytest.skip("arterial_lh not generated")
    links, heading, lefthand = net_links(net)
    assert lefthand and len(links) == 6
    phases = {f"P{k}": Phase(f"P{k}", frozenset(f"L{5 * k + j}" for j in range(5)))
              for k in range(4)}
    conflicts: dict[str, set[str]] = {m: set() for m in links["C0"]}
    import xml.etree.ElementTree as ET

    root = ET.parse(net).getroot()
    for j in root.findall("junction"):
        if j.get("id") == "C0":
            for r in j.findall("request"):
                i = int(r.get("index"))
                foes = r.get("foes")[::-1]
                conflicts[f"L{i}"] |= {f"L{k}" for k, c in enumerate(foes) if c == "1"}
    sym = {m: frozenset(c | {o for o, cs in conflicts.items() if m in cs})
           for m, c in conflicts.items()}
    cfg = Tier0Config(intersection_id="C0", phases=phases, ring_order=tuple(phases),
                      conflict_matrix=sym, min_green_s=dict.fromkeys(phases, 7.0),
                      max_green_s=dict.fromkeys(phases, 40.0), yellow_s=3.5, all_red_s=2.0)
    out = paired_layout(cfg, links["C0"], heading, lefthand)
    assert len(out.phases) == 2
    permissive = set().union(*(p.green_movements - p.protected_movements
                               for p in out.phases.values()))
    assert {links["C0"][m][1] for m in permissive} == {"r"}


def test_compact_layout_finds_the_two_phase_plan_and_turns_yield() -> None:
    from itms_domain.phase_layout import compact_layout

    out = compact_layout(_cfg(_CONFLICTS), _LINKS, _APPROACH, lefthand=True)
    assert len(out.phases) == 2 and out.validate() == []
    served = set().union(*(p.green_movements for p in out.phases.values()))
    assert served == set(_LINKS)
    permissive = set().union(*(p.green_movements - p.protected_movements
                               for p in out.phases.values()))
    assert {_LINKS[m][1] for m in permissive} == {"r"}


def test_compact_layout_never_puts_two_crossing_turns_that_cross_together() -> None:
    from itms_domain.phase_layout import compact_layout

    clashing = {**_CONFLICTS, "L2": _CONFLICTS["L2"] | {"L5"}}
    out = compact_layout(_cfg(clashing), _LINKS, _APPROACH, lefthand=True)
    assert out.validate() == []
    assert not any({"L2", "L5"} <= p.green_movements for p in out.phases.values())


def test_compact_layout_leaves_a_junction_that_cannot_lose_a_phase() -> None:
    from itms_domain.phase_layout import compact_layout

    # every straight crosses every other: four phases are already the fewest
    allx = {**_CONFLICTS, "L1": _CONFLICTS["L1"] | {"L4"}, "L7": {"L10", "L1", "L4"}}
    cfg = _cfg(allx)
    assert compact_layout(cfg, _LINKS, _APPROACH, lefthand=True) is cfg
