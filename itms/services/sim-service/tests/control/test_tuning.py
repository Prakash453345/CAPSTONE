"""`control/tuning.py` -- the parameter learner.

Optimizer tests are run against cheap analytic objectives, not against
SUMO: the question here is whether the search machinery works (bounds
respected, vectors round-trip, a known optimum is found, the safety
penalty actually dominates), and a stochastic 90-second simulation is a
bad instrument for answering it. `scripts/train_acamp.py` is where the
same code meets the real evaluator.
"""

from __future__ import annotations

import math

from sim_service.control.strategies.acamp import AcampConfig
from sim_service.control.tuning import (
    PARAM_SPACE,
    EvaluationResult,
    TuningHistory,
    from_vector,
    load_config,
    optimize,
    save_config,
    to_vector,
)


def test_vector_round_trip_is_the_identity():
    cfg = AcampConfig(eta_arrival=0.42, rho_jam=0.66, kappa_switch=1.7, alpha_switch=0.31, k=3)
    assert from_vector(to_vector(cfg), cfg) == cfg


def test_from_vector_clips_to_bounds():
    """CMA-ES samples from an unbounded Gaussian and will routinely
    propose values outside the box. Clipping rather than rejecting,
    because several parameters plausibly have their optimum *at* a bound
    -- `eta_arrival = 0` is the finding "anticipation does not help
    here", which the search must be able to express and report."""
    wild = [1e6] * len(PARAM_SPACE)
    cfg = from_vector(wild)
    for name, (low, high) in PARAM_SPACE.items():
        value = getattr(cfg, name)
        assert low - 1e-9 <= value <= high + 1e-9, f"{name}={value} escaped [{low}, {high}]"

    cfg_low = from_vector([-1e6] * len(PARAM_SPACE))
    for name, (low, high) in PARAM_SPACE.items():
        assert low - 1e-9 <= getattr(cfg_low, name) <= high + 1e-9


def test_alpha_switch_can_never_leave_the_open_unit_interval():
    """The one search bound carrying a theoretical claim rather than a
    practical one. `alpha = 0` reproduces M4's constant switching cost
    exactly; `alpha = 1` never becomes negligible against pressure.
    Neither is reachable from any vector the optimizer can produce, so
    the sublinearity condition throughput-optimality rests on cannot be
    traded away for delay."""
    for extreme in (-1e9, 0.0, 1.0, 1e9):
        vector = [extreme] * len(PARAM_SPACE)
        cfg = from_vector(vector)
        assert 0.0 < cfg.alpha_switch < 1.0


def test_integer_parameters_are_integral():
    """`k` is a ring-lookahead depth. A `k` of 2.4 would be silently
    truncated somewhere downstream; rounding here makes the search space
    honest about what it is optimizing."""
    cfg = from_vector([2.6] * len(PARAM_SPACE))
    assert isinstance(cfg.k, int)


def test_objective_ranks_violations_above_any_delay_difference():
    """A parameter set that leans on the safety net to stay safe is a bad
    parameter set even though it is never an unsafe one. No delay
    improvement may buy a single violation."""
    clean = EvaluationResult(person_delay_s=1.5, interlock_violations=0, completed_trips=100, seeds=2)
    one_violation = EvaluationResult(
        person_delay_s=0.5, interlock_violations=1, completed_trips=100, seeds=2
    )
    assert clean.objective < one_violation.objective


def test_violation_penalty_is_scale_free():
    """The penalty is multiplicative because this objective is fed delay
    on two different scales: raw person-seconds by a single-level caller,
    and Webster-normalized O(1) values by `train_acamp.py`, which must put
    three demand levels on a common footing before averaging. An additive
    constant sized for one scale is inert or infinite on the other -- a
    real bug this test exists to prevent recurring."""
    for scale in (1.0, 1e3, 1e6):
        clean = EvaluationResult(
            person_delay_s=0.9 * scale, interlock_violations=0, completed_trips=10, seeds=1
        )
        dirty = EvaluationResult(
            person_delay_s=0.1 * scale, interlock_violations=1, completed_trips=10, seeds=1
        )
        worse = EvaluationResult(
            person_delay_s=0.1 * scale, interlock_violations=9, completed_trips=10, seeds=1
        )
        assert clean.objective < dirty.objective < worse.objective, f"failed at scale {scale}"


def test_objective_rejects_a_gridlocked_run():
    """A run that completed no trips has an excellent-looking delay
    figure, computed over no vehicles. It must not win."""
    gridlock = EvaluationResult(person_delay_s=0.0, interlock_violations=0, completed_trips=0, seeds=2)
    assert math.isinf(gridlock.objective)


def test_optimizer_finds_a_known_optimum():
    """End-to-end check of the search loop against an analytic objective
    whose optimum is known: minimize distance to a target parameter
    vector. Confirms the normalization, ask/tell wiring and bound
    handling actually cooperate, which no unit test of the pieces
    does."""
    target = AcampConfig(eta_arrival=1.2, rho_jam=0.9, beta_gate=3.0, lambda_f=2.0, gamma=5.0,
                         kappa_switch=4.0, alpha_switch=0.8, k=4)
    target_vec = to_vector(target)

    def evaluate(cfg: AcampConfig) -> EvaluationResult:
        vec = to_vector(cfg)
        spans = [hi - lo for lo, hi in PARAM_SPACE.values()]
        dist = sum(((a - b) / s) ** 2 for a, b, s in zip(vec, target_vec, spans, strict=True))
        return EvaluationResult(person_delay_s=dist, interlock_violations=0, completed_trips=1, seeds=1)

    start = AcampConfig()
    best, history = optimize(evaluate, base=start, generations=25, population=10, sigma0=0.3, seed=7)

    def dist_to_target(cfg: AcampConfig) -> float:
        spans = [hi - lo for lo, hi in PARAM_SPACE.values()]
        return sum(((a - b) / s) ** 2 for a, b, s in zip(to_vector(cfg), target_vec, spans, strict=True))

    assert dist_to_target(best) < dist_to_target(start) / 10.0
    assert len(history.entries) == 25 * 10
    assert history.best()["objective"] <= min(e["objective"] for e in history.entries)


def test_optimizer_steers_out_of_a_graded_violation_region():
    """What the count-scaled penalty actually buys, tested against the
    shape violations really have on this corridor.

    PROGRESS.md's M4 numbers are 0, 3 and 10,235 violations across
    neighbouring configurations -- a steep, informative slope, not a
    binary flag. Modelled here as violations growing with
    `kappa_switch` (a stickier controller starves more movements), with
    delay pulling the opposite way so the search has a genuine tradeoff
    to resolve rather than a single dominant direction."""

    def evaluate(cfg: AcampConfig) -> EvaluationResult:
        excess = max(0.0, cfg.kappa_switch - 2.0)
        return EvaluationResult(
            person_delay_s=1000.0 - 10.0 * cfg.kappa_switch,
            interlock_violations=int(excess**2 * 400),
            completed_trips=100,
            seeds=1,
        )

    best, _ = optimize(
        evaluate, base=AcampConfig(kappa_switch=4.5), generations=15, population=8, seed=3
    )
    assert best.kappa_switch <= 2.1, f"search stayed in the violating region at {best.kappa_switch}"


def test_a_binary_violation_region_is_flat_and_the_penalty_does_not_help():
    """The counterpart to the test above, recorded rather than hidden:
    where violations flip 0 -> 1 and go no further, the penalized region
    is flat and the finite penalty provides no directional information
    at all. The search can start inside such a region and stay there.

    Asserted as the actual behaviour rather than papered over, because
    the honest scope of the safety penalty is "ranks violating candidates
    correctly, and steers when counts vary" -- not "guarantees the search
    leaves any unsafe region". The guarantee that a tuned controller is
    safe comes from `interlocks.check`, which no parameter can reach, and
    never from this objective."""

    def evaluate(cfg: AcampConfig) -> EvaluationResult:
        return EvaluationResult(
            person_delay_s=1000.0 - 10.0 * cfg.kappa_switch,
            interlock_violations=1 if cfg.kappa_switch > 2.0 else 0,
            completed_trips=100,
            seeds=1,
        )

    best, history = optimize(
        evaluate, base=AcampConfig(kappa_switch=4.5), generations=15, population=8, seed=3
    )
    # It does still *rank* correctly: had the search sampled a clean
    # candidate, that candidate would have won outright.
    clean = [e for e in history.entries if e["interlock_violations"] == 0]
    dirty = [e for e in history.entries if e["interlock_violations"] > 0]
    if clean and dirty:
        assert max(e["objective"] for e in clean) < min(e["objective"] for e in dirty)


def test_history_records_every_evaluation_in_order():
    """The search trace is a result in its own right: it answers "which
    parameters was the objective actually sensitive to" for all of them
    at once, from data the search had to generate anyway. M4 answered
    that question one parameter at a time, expensively."""
    history = TuningHistory()
    calls = {"n": 0}

    def evaluate(cfg: AcampConfig) -> EvaluationResult:
        calls["n"] += 1
        return EvaluationResult(person_delay_s=float(calls["n"]), interlock_violations=0,
                                completed_trips=10, seeds=1)

    optimize(evaluate, generations=3, population=4, history=history, seed=11)
    assert len(history.entries) == 12
    assert [e["generation"] for e in history.entries] == [0] * 4 + [1] * 4 + [2] * 4
    assert history.best()["person_delay_s"] == 1.0


def test_config_save_load_round_trip(tmp_path):
    cfg = AcampConfig(eta_arrival=0.77, alpha_switch=0.41, k=3)
    path = tmp_path / "tuned.json"
    save_config(cfg, path)
    assert load_config(path) == cfg


def test_load_ignores_unknown_keys_and_defaults_missing_ones(tmp_path):
    """A config saved before a parameter was added to `PARAM_SPACE` must
    still load, with the new parameter at its default -- the correct
    reading of "this file predates that knob"."""
    path = tmp_path / "old.json"
    path.write_text('{"eta_arrival": 0.9, "a_removed_knob": 1.0}')
    cfg = load_config(path)
    assert cfg.eta_arrival == 0.9
    assert cfg.alpha_switch == AcampConfig().alpha_switch
