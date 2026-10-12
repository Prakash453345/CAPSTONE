"""`itms_domain.signal_program`: the states of a real signal program that
are phases a controller chooses between."""

from __future__ import annotations

from itms_domain.signal_program import green_phase_states, is_green_phase, sub_stage_indices


def test_amber_and_red_amber_make_a_change_interval() -> None:
    assert is_green_phase("GGrr") and is_green_phase("ggGG")
    assert not is_green_phase("yyGr")        # one movement carries on through a change
    assert not is_green_phase("uuGr")        # red+amber before green (German plans)
    assert not is_green_phase("rrrr")


def test_a_pedestrian_clearance_is_part_of_its_stage() -> None:
    # vehicles L0-L1 green with the crossing L3, then the crossing red, then amber
    states = ["GGrG", "GGrr", "yyrr", "rrGr", "rryr"]
    assert sub_stage_indices(states) == {1}
    assert green_phase_states(states) == [(0, "GGrG"), (3, "rrGr")]


def test_a_start_up_signal_does_not_end_a_stage_but_amber_does() -> None:
    # SUMO's Ingolstadt plan: a 1 s head, red+amber for the rest, the full stage
    states = ["rrrr", "rrGr", "uuGr", "GGGr", "yyyr", "rrrG", "rrry"]
    assert sub_stage_indices(states) == {1}
    assert [s for _, s in green_phase_states(states)] == ["GGGr", "rrrG"]
    # the same subset after an amber is a stage of its own
    assert sub_stage_indices(["GGGr", "yyGr", "rrGr", "rryr"]) == set()


def test_a_green_that_protects_what_the_other_only_permits_is_its_own_phase() -> None:
    assert sub_stage_indices(["GGg", "rrG", "yyy"]) == set()


def test_the_same_green_twice_in_a_cycle_is_one_phase() -> None:
    assert green_phase_states(["GGrr", "yyrr", "rrGG", "rryy", "GGrr", "yyrr"]) == [
        (0, "GGrr"), (2, "rrGG")]
