"""Unit tests for `SpillbackTracker`'s episode-counting logic --
`sample()` calls live TraCI internally (`traci.lane.getLastStepOccupancy`),
so these monkeypatch that one call to drive deterministic occupancy
sequences without a real SUMO process, the same "swap in a small fake
where I/O is inherently stateful" spirit as `FakeCabinet`."""

from __future__ import annotations

from sim_service.signal_controller import spillback as spillback_module
from sim_service.signal_controller.spillback import SpillbackTracker


def _fake_occupancies(monkeypatch, sequence: list[dict[str, float]]):
    """Feed one `{lane_id: occupancy_fraction}` dict per call to `sample()`,
    in order. TraCI's own `getLastStepOccupancy` returns a fraction in
    [0, 1], so these fixtures do too."""
    calls = iter(sequence)
    current: dict[str, float] = {}

    def _get_last_step_occupancy(lane_id: str) -> float:
        return current[lane_id]

    def _advance():
        nonlocal current
        current = next(calls)

    monkeypatch.setattr(
        spillback_module.traci.lane, "getLastStepOccupancy", _get_last_step_occupancy
    )
    return _advance


def test_a_single_full_episode_counts_once_even_while_sustained(monkeypatch):
    advance = _fake_occupancies(
        monkeypatch,
        [
            {"L0": 0.50},  # not full
            {"L0": 0.95},  # rising edge -- episode 1
            {"L0": 0.96},  # still full -- not a new episode
            {"L0": 0.97},  # still full -- not a new episode
        ],
    )
    tracker = SpillbackTracker(["L0"])
    for _ in range(4):
        advance()
        tracker.sample()
    assert tracker.episode_count == 1


def test_clearing_and_refilling_counts_two_episodes(monkeypatch):
    advance = _fake_occupancies(
        monkeypatch,
        [
            {"L0": 0.95},  # episode 1 starts
            {"L0": 0.50},  # clears
            {"L0": 0.95},  # episode 2 starts
        ],
    )
    tracker = SpillbackTracker(["L0"])
    for _ in range(3):
        advance()
        tracker.sample()
    assert tracker.episode_count == 2


def test_occupancy_exactly_at_threshold_counts_as_full(monkeypatch):
    # 90.0 (TraCI's 0-100 percentage) / 100 == 0.9 exactly -- the ">="
    # boundary should count, not require strictly exceeding it.
    advance = _fake_occupancies(monkeypatch, [{"L0": 0.90}])
    tracker = SpillbackTracker(["L0"], occupancy_threshold=0.9)
    advance()
    tracker.sample()
    assert tracker.episode_count == 1


def test_lanes_are_tracked_independently(monkeypatch):
    advance = _fake_occupancies(
        monkeypatch,
        [
            {"L0": 0.95, "L1": 0.10},  # L0 episode 1
            {"L0": 0.95, "L1": 0.95},  # L1 episode 1, L0 still full (no new episode)
            {"L0": 0.10, "L1": 0.95},  # L0 clears, L1 still full
        ],
    )
    tracker = SpillbackTracker(["L0", "L1"])
    for _ in range(3):
        advance()
        tracker.sample()
    assert tracker.episode_count == 2


def test_never_reaching_the_threshold_counts_zero_episodes(monkeypatch):
    advance = _fake_occupancies(monkeypatch, [{"L0": 0.10}, {"L0": 0.20}, {"L0": 0.899}])
    tracker = SpillbackTracker(["L0"], occupancy_threshold=0.9)
    for _ in range(3):
        advance()
        tracker.sample()
    assert tracker.episode_count == 0
