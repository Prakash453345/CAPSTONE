"""`itms_domain.overlaps.with_overlaps`: a movement is added to every phase it
conflicts with nothing in -- read both ways off the conflict matrix, against
what the phase shows (permissive movements included) and what was already
added -- and nothing else changes."""

from __future__ import annotations

from itms_domain.overlaps import pedestrian_links, with_overlaps
from itms_domain.signal import Phase, Tier0Config


def _cfg(phases: dict[str, Phase], conflicts: dict[str, set[str]]) -> Tier0Config:
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=tuple(p for p in phases if not phases[p].is_pedestrian),
        conflict_matrix={m: frozenset(c) for m, c in conflicts.items()},
        min_green_s=dict.fromkeys(phases, 7.0),
        max_green_s=dict.fromkeys(phases, 40.0),
        yellow_s=3.0,
        all_red_s=2.0,
    )


def _greens(cfg: Tier0Config) -> dict[str, set[str]]:
    return {p: set(ph.green_movements) for p, ph in cfg.phases.items()}


def test_a_movement_runs_in_every_phase_it_fits_and_never_beside_a_foe() -> None:
    # L0, L1 through one way; L2 across them; L3 a turn that only crosses L1
    cfg = _cfg({"P1": Phase("P1", frozenset({"L0", "L1"})),
                "P2": Phase("P2", frozenset({"L2"})),
                "P3": Phase("P3", frozenset({"L3"}))},
               {"L0": {"L2"}, "L1": {"L2", "L3"}, "L2": {"L0", "L1"}, "L3": {"L1"}})
    out = with_overlaps(cfg)
    # P2 takes the turn; P3 takes L0 and then not L2, which crosses the L0 just added
    assert _greens(out) == {"P1": {"L0", "L1"}, "P2": {"L2", "L3"}, "P3": {"L3", "L0"}}
    assert out.phases["P2"].protected_movements == frozenset({"L2", "L3"})
    assert out.validate() == []
    for ph in out.phases.values():
        shown = ph.green_movements
        assert not any(b in cfg.conflict_matrix.get(a, ()) for a in shown for b in shown)


def test_a_one_sided_conflict_and_a_permissive_movement_both_block() -> None:
    # L3 is listed as a foe only by L1 (SUMO's foes can be one-sided), and
    # L1 is shown permissive in P1: the turn still stays out of P1
    cfg = _cfg({"P1": Phase("P1", frozenset({"L0", "L1"}), protected_movements=frozenset({"L0"})),
                "P2": Phase("P2", frozenset({"L3"}))},
               {"L1": {"L3"}})
    assert _greens(with_overlaps(cfg)) == {"P1": {"L0", "L1"}, "P2": {"L3", "L0"}}


def test_pedestrian_phases_and_unsignalled_movements_are_left_alone() -> None:
    cfg = _cfg({"P1": Phase("P1", frozenset({"L0"})),
                "W": Phase("W", frozenset({"L5"}), is_pedestrian=True)},
               {"L0": {"L5"}, "L5": {"L0"}})
    out = with_overlaps(cfg)
    assert out.phases["W"] is cfg.phases["W"]
    assert _greens(out) == {"P1": {"L0"}, "W": {"L5"}}
    # nothing to add: the same phases come back
    assert out.phases["P1"] is cfg.phases["P1"]


def test_a_pedestrian_signal_is_never_added(tmp_path) -> None:
    cfg = _cfg({"P1": Phase("P1", frozenset({"L0"})), "P2": Phase("P2", frozenset({"L1"}))}, {})
    assert _greens(with_overlaps(cfg, exclude={"L1"})) == {"P1": {"L0"}, "P2": {"L1", "L0"}}
    net = tmp_path / "n.net.xml"
    net.write_text("""<net>
      <edge id=":J_c0" function="crossing"/><edge id=":J_w0" function="walkingarea"/>
      <connection from="a" to="b" fromLane="0" toLane="0" tl="J" linkIndex="0"/>
      <connection from=":J_w0" to=":J_c0" fromLane="0" toLane="0" tl="J" linkIndex="1"/>
    </net>""")
    assert pedestrian_links(net) == {"J": frozenset({"L1"})}



def test_unowned_overlaps_are_shown_but_leave_the_phase_as_it_was() -> None:
    """`owned=False`: the same movements, in `overlap_movements`; the phase's own
    movements (what a controller and a timing plan read) are untouched."""
    cfg = _cfg({"P1": Phase("P1", frozenset({"L0", "L1"})),
                "P2": Phase("P2", frozenset({"L2"})),
                "P3": Phase("P3", frozenset({"L3"}))},
               {"L0": {"L2"}, "L1": {"L2", "L3"}, "L2": {"L0", "L1"}, "L3": {"L1"}})
    out = with_overlaps(cfg, owned=False)
    assert _greens(out) == _greens(cfg)
    assert {p: set(ph.overlap_movements) for p, ph in out.phases.items()} == {
        "P1": set(), "P2": {"L3"}, "P3": {"L0"}}
    assert out.phases["P3"].shown_movements == frozenset({"L3", "L0"})
    assert out.validate() == []
