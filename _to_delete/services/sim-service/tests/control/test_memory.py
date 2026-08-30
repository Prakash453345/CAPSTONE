"""`control/memory.py` -- the cross-run demand profile.

The properties that matter here are mostly about *not* being confidently
wrong: an unvisited bin must stay unknown rather than become a zero, a
one-run bin must report as unavailable rather than as a low-confidence
number, and an interrupted save must not leave a file the next run would
load as real history.
"""

from __future__ import annotations

import json

from sim_service.control.memory import DemandMemory, blend


def _run(mem: DemandMemory, junction: str, queue: float, ticks: int = 10, t0: float = 0.0) -> None:
    for i in range(ticks):
        mem.observe_tick(junction, t0 + i, {"m0": queue}, {"m0": queue * 0.5})
    mem.end_run()


def test_profile_unavailable_below_min_runs():
    """One run at one junction in one 15-minute bin is a single sample of
    a stochastic process. Reporting it as "what usually happens" would be
    exactly the overconfidence this module exists to avoid."""
    mem = DemandMemory(min_runs=2)
    _run(mem, "J", 10.0)
    assert mem.profile("J", "m0", 5.0) is None
    _run(mem, "J", 10.0)
    assert mem.profile("J", "m0", 5.0) is not None


def test_ewma_tracks_a_demand_shift():
    """The reason it is an EWMA and not a running mean: a controller
    whose memory cannot forget is worse than one with none, because it is
    confidently wrong rather than merely ignorant."""
    mem = DemandMemory(min_runs=1, decay=0.7)
    for _ in range(5):
        _run(mem, "J", 4.0)
    settled, _ = mem.profile("J", "m0", 5.0)
    assert abs(settled - 4.0) < 0.5

    for _ in range(6):
        _run(mem, "J", 20.0)
    shifted, _ = mem.profile("J", "m0", 5.0)
    assert shifted > 15.0, f"EWMA failed to track the shift, sitting at {shifted}"


def test_short_run_does_not_dilute_a_bin_it_never_reached():
    """"No vehicle was observed here" and "this bin was never sampled"
    are different facts. Averaging the second in as the first would drag
    every profile toward zero in proportion to how often a run ended
    early -- and since a run ends when its last vehicle arrives, the runs
    that end earliest are the light-demand ones, so the bias would land
    hardest on exactly the busy bins a profile is most useful for.

    Set up so a wrong implementation fails visibly: two long runs
    establish bin 1 at 30.0, then two short runs never reach it. Folding
    their absence in as a zero would pull bin 1 down toward 15; leaving it
    untouched keeps it at 30."""
    mem = DemandMemory(min_runs=2, bin_width_s=100.0, decay=0.5)
    for _ in range(2):
        for i in range(10):
            mem.observe_tick("J", float(i), {"m0": 5.0}, {"m0": 0.0})
            mem.observe_tick("J", 100.0 + i, {"m0": 30.0}, {"m0": 0.0})
        mem.end_run()
    established, _ = mem.profile("J", "m0", 150.0)
    assert abs(established - 30.0) < 1e-6

    for _ in range(2):
        _run(mem, "J", 5.0, ticks=10, t0=0.0)  # bin 0 only -- never reaches bin 1
    after, _ = mem.profile("J", "m0", 150.0)
    assert after == established, f"bin 1 was diluted to {after} by runs that never visited it"


def test_in_progress_run_does_not_contaminate_its_own_history():
    """`profile()` during a run must read only what *previous* runs
    committed. Otherwise a controller blending against memory would be
    blending against a rolling average of its own current behaviour, and
    would converge on itself."""
    mem = DemandMemory(min_runs=1)
    _run(mem, "J", 5.0)
    _run(mem, "J", 5.0)
    before, _ = mem.profile("J", "m0", 5.0)
    for i in range(50):
        mem.observe_tick("J", float(i), {"m0": 100.0}, {"m0": 0.0})
    during, _ = mem.profile("J", "m0", 5.0)
    assert during == before


def test_bins_separate_by_time_of_day():
    """The whole point of a time-of-day profile: a morning peak must not
    be averaged into an afternoon lull."""
    mem = DemandMemory(min_runs=1, bin_width_s=100.0)
    for _ in range(2):
        for i in range(10):
            mem.observe_tick("J", float(i), {"m0": 2.0}, {"m0": 0.0})
            mem.observe_tick("J", 500.0 + i, {"m0": 30.0}, {"m0": 0.0})
        mem.end_run()
    quiet, _ = mem.profile("J", "m0", 50.0)
    busy, _ = mem.profile("J", "m0", 550.0)
    assert quiet < 5.0 < busy


def test_save_load_round_trip(tmp_path):
    mem = DemandMemory(min_runs=1, decay=0.6, bin_width_s=300.0)
    _run(mem, "J1", 12.0)
    _run(mem, "J1", 12.0)
    _run(mem, "J2", 3.0)
    _run(mem, "J2", 3.0)
    path = tmp_path / "profile.json"
    mem.save(path)

    restored = DemandMemory.load(path)
    assert restored.decay == 0.6
    assert restored.bin_width_s == 300.0
    assert restored.profile("J1", "m0", 5.0) == mem.profile("J1", "m0", 5.0)
    assert restored.profile("J2", "m0", 5.0) == mem.profile("J2", "m0", 5.0)


def test_save_is_atomic(tmp_path):
    """Write-then-rename: a run interrupted mid-save must not leave a
    truncated profile the next run would load as real history. Checked by
    confirming no partial file survives alongside the real one and that
    the result parses."""
    mem = DemandMemory(min_runs=1)
    _run(mem, "J", 7.0)
    _run(mem, "J", 7.0)
    path = tmp_path / "nested" / "profile.json"
    mem.save(path)
    assert path.exists()
    assert not list(path.parent.glob("*.tmp"))
    json.loads(path.read_text())


def test_load_missing_file_is_a_cold_start_not_an_error(tmp_path):
    mem = DemandMemory.load(tmp_path / "does-not-exist.json")
    assert mem.coverage() == (0, 0)
    assert mem.profile("J", "m0", 0.0) is None


def test_coverage_reports_usable_versus_total():
    """A gate result quoting "with demand memory" while coverage was 0/N
    would be a claim about code that never executed."""
    mem = DemandMemory(min_runs=2)
    _run(mem, "J", 4.0)
    usable, total = mem.coverage()
    assert usable == 0 and total > 0
    _run(mem, "J", 4.0)
    usable, total = mem.coverage()
    assert usable == total > 0


# ---- blend -----------------------------------------------------------


def test_blend_returns_live_when_history_is_absent():
    """With nothing to blend toward, a partially-trusted live reading is
    still strictly better than shrinking it toward an invented zero --
    which is what a `historical or 0.0` default would silently do."""
    assert blend(9.0, None, 0.3) == 9.0


def test_blend_is_confidence_weighted():
    assert blend(10.0, 0.0, 1.0) == 10.0
    assert blend(10.0, 0.0, 0.0) == 0.0
    assert blend(10.0, 20.0, 0.5) == 15.0


def test_blend_clamps_out_of_range_confidence():
    """`confidence` arrives from what will be a vision pipeline's output.
    A control path is the wrong place to discover an upstream service
    emitted 1.02."""
    assert blend(10.0, 0.0, 1.5) == 10.0
    assert blend(10.0, 0.0, -0.5) == 0.0
