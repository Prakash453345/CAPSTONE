"""Parameter learning for A-CA-MP -- the layer that turns "10 interacting
constants a person picks by hand" into "10 numbers fitted to measured
outcomes".

**Why this exists, from this project's own history.** PROGRESS.md records
a multi-session manual search over `CampConfig`: a `hysteresis_frac`
sweep that came back bit-identical at every seed (the parameter was
inert), a diagnostic instrumentation run to discover `S(p)` was 22-61x
typical flow pressure, a rescale of `S(p)`, a structural starvation
deadlock the rescale then caused, and a starvation override to contain
it. Every step was competent and each finding was real. The conclusion to
draw is not that the constants were chosen badly -- it is that fitting
~10 interacting parameters against a stochastic simulator by hand, one
hypothesis at a time, is not a task a person should be doing manually.
That is a numerical optimization problem, and this module is the
optimizer.

**Why CMA-ES and not PPO/DQN.** The learned object here is a 8-parameter
real vector, not a policy network. For that regime:

- CMA-ES needs no gradient, no replay buffer, no target network, no
  reward shaping, and no credit assignment across timesteps -- the
  objective is one number per full scenario run, which is exactly the
  signal a SUMO run naturally produces and exactly what an episodic
  black-box optimizer consumes.
- It is invariant to monotone transformations of the objective and to
  rotations of the search space, so it does not care that person-delay
  is heavy-tailed or that `kappa_switch` and `alpha_switch` interact
  multiplicatively.
- The comparison is honest about sample budget: a deep-RL controller for
  this corridor would need `O(10^6)` simulated steps before it beat a
  tuned baseline; this needs `O(10^2)` full runs, which is the difference
  between an overnight job and a compute allocation.

The tradeoff is real and stated: CMA-ES fits *parameters of a fixed,
interpretable control law*. It cannot discover a control law the
parameterization cannot express. A DQN over raw state can, in principle,
and would be the right tool if the goal were maximum achievable
performance regardless of explicability. It is the wrong tool here
because the resulting controller could not be reasoned about against the
safety kernel, and because every parameter this module fits stays
readable afterwards -- `alpha_switch = 0.31` is a statement about how
switching resistance should scale with congestion, which a person can
argue with. A weight matrix is not.

**Safety is not learned, and cannot be unlearned.** No parameter in
`PARAM_SPACE` can reach an interlock: `Tier0Config`'s min-green, clearance
intervals, conflict matrix and max-wait bound are Tier-0 and are not in
the search space at all, and every proposal a tuned controller makes
still passes `interlocks.check()` before it reaches a cabinet. This is
the shielding pattern the safe-RL literature builds explicitly [Alshiekh
et al.; Müller et al. 2022 on action masking for signal control] -- this
project already had it, built for a different reason, two milestones
before it needed it. The objective still penalizes violations heavily
(see `EvaluationResult.objective`) because a parameter set that leans on
the safety net to stay safe is a bad parameter set even though it is
never an unsafe one; the distinction matters and the penalty encodes it.

`alpha_switch`'s bound is the one place a search bound carries a
theoretical claim rather than a practical one: it is held strictly inside
`(0, 1)` so `sublinear_hold_bias` keeps the sublinearity condition
throughput-optimality depends on. The optimizer is not permitted to
trade that away for delay, which is why it is a bound and not a
penalty.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from sim_service.control.strategies.acamp import AcampConfig

# name -> (low, high). Order defines the vector layout and is load-bearing:
# `to_vector`/`from_vector` both iterate this dict, so a saved vector and
# the code that reads it agree only as long as this ordering is stable.
# Appending a parameter is safe; reordering silently invalidates every
# previously-saved vector, so don't.
PARAM_SPACE: dict[str, tuple[float, float]] = {
    "eta_arrival": (0.0, 1.5),
    "rho_jam": (0.30, 0.98),
    "beta_gate": (0.5, 4.0),
    "lambda_f": (0.0, 3.0),
    "gamma": (1.0, 6.0),
    "kappa_switch": (0.0, 5.0),
    # Strictly inside (0,1): see module docstring. 0.05/0.95 rather than
    # 0.0/1.0 so a bound-hitting solution is still a legal one --
    # `sublinear_hold_bias` raises on the open-interval violation, and an
    # optimizer that can propose a crashing candidate wastes evaluations
    # discovering that.
    "alpha_switch": (0.05, 0.95),
    "k": (1.0, 4.0),
}

_INTEGER_PARAMS = frozenset({"k"})


def to_vector(cfg: AcampConfig) -> list[float]:
    return [float(getattr(cfg, name)) for name in PARAM_SPACE]


def from_vector(vector: Sequence[float], base: AcampConfig | None = None) -> AcampConfig:
    """Map an optimizer's raw vector onto a valid `AcampConfig`.

    Clipping to bounds happens here rather than being left to the
    optimizer: CMA-ES samples from an unbounded Gaussian and will
    routinely propose values outside the box, and the two honest ways to
    handle that are to clip or to reject-and-resample. Clipping is chosen
    because rejection biases the sampling distribution near a bound, and
    several of these parameters have their optimum plausibly *at* a bound
    (`eta_arrival` at 0 would be the finding "anticipation does not help
    here", which the search must be able to express and report)."""
    base = base or AcampConfig()
    values: dict[str, float | int] = {}
    for raw, (name, (low, high)) in zip(vector, PARAM_SPACE.items(), strict=True):
        clipped = min(high, max(low, float(raw)))
        values[name] = int(round(clipped)) if name in _INTEGER_PARAMS else clipped
    return replace(base, **values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class EvaluationResult:
    """One candidate's measured performance, aggregated over its seeds."""

    person_delay_s: float
    interlock_violations: int
    completed_trips: int
    seeds: int

    @property
    def objective(self) -> float:
        """Lower is better -- CMA-ES minimizes.

        Person-delay is the primary term because it is the gate's own
        metric, so a tuned controller is optimized against the same
        quantity it will be judged on rather than a proxy that correlates
        with it.

        Interlock violations carry a large additive penalty, scaled by the
        violation *count*, rather than being a hard rejection. The
        count-scaling is the part that does the work, and it is worth
        being precise about why, because the obvious justification is
        wrong:

        It is tempting to say "finite rather than infinite so the search
        has a gradient to follow out of the unsafe region". That is only
        true where the violation count actually varies. Where a parameter
        change flips violations from 0 to 1 and no further, the penalized
        region is *flat* -- `1e7 + delay` for every candidate in it -- and
        a finite penalty gives the optimizer no more directional
        information than an infinite one would. A test written against a
        binary violation confirmed exactly this: CMA-ES random-walked
        inside the region and returned a violating candidate.

        What makes count-scaling worth having is that on the real
        corridor violations are emphatically *not* binary. PROGRESS.M4
        records a single starved movement producing 10,235 rejections in
        one run, against 0 in a neighbouring configuration and 3 in
        another. Across that range the penalty is a steep, informative
        slope, and a candidate that starves one movement briefly is
        correctly ranked far above one that deadlocks a junction for the
        rest of the run. Both are rejected; the search learns which
        direction is less bad.

        The magnitude is set well above any plausible delay difference so
        that no amount of delay improvement can buy even one violation.

        A run that completed no trips scores as infinite: that is a
        controller that gridlocked the corridor, and its delay figure
        (computed over the vehicles that did finish -- none) would
        otherwise read as excellent."""
        if self.completed_trips <= 0:
            return math.inf
        return self.person_delay_s + 1e7 * self.interlock_violations


@dataclass
class TuningHistory:
    """Every candidate the search ever evaluated, in order.

    Kept in full, and saved, because the *search trace* is a result in its
    own right for this project: it shows which parameters the objective
    was actually sensitive to and which it was indifferent about. M4's
    `hysteresis_frac` sweep discovered inertness the expensive way, one
    parameter at a time; a full trace answers that question for all eight
    at once, from data the search had to generate anyway."""

    entries: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.entries is None:
            self.entries = []

    def record(self, generation: int, cfg: AcampConfig, result: EvaluationResult) -> None:
        self.entries.append(
            {
                "generation": generation,
                "params": {name: getattr(cfg, name) for name in PARAM_SPACE},
                "person_delay_s": result.person_delay_s,
                "interlock_violations": result.interlock_violations,
                "completed_trips": result.completed_trips,
                "seeds": result.seeds,
                "objective": result.objective,
            }
        )

    def best(self) -> dict | None:
        finite = [e for e in self.entries if math.isfinite(e["objective"])]
        return min(finite, key=lambda e: e["objective"]) if finite else None

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"entries": self.entries, "best": self.best()}, indent=2)
        )


def optimize(
    evaluate: Callable[[AcampConfig], EvaluationResult],
    *,
    base: AcampConfig | None = None,
    generations: int = 8,
    population: int = 6,
    sigma0: float = 0.25,
    seed: int = 0,
    history: TuningHistory | None = None,
    on_generation: Callable[[int, AcampConfig, EvaluationResult], None] | None = None,
) -> tuple[AcampConfig, TuningHistory]:
    """Run CMA-ES over `PARAM_SPACE`, returning the best config found and
    the full search trace.

    Optimizes in a *normalized* `[0, 1]` box rather than in the raw
    parameter units, so that one CMA-ES step size is meaningful for
    `alpha_switch` (range 0.9) and `gamma` (range 5.0) simultaneously.
    Without normalization a `sigma0` large enough to explore `gamma` would
    slam `alpha_switch` into its bounds on every sample.

    Falls back to a plain `(mu, lambda)` evolution strategy if the `cma`
    package is unavailable, rather than failing: the fallback is
    materially weaker (no covariance adaptation, so it cannot learn that
    two parameters interact) but it is a real optimizer, and a training
    script that refuses to run without an optional dependency is worse
    than one that runs and says what it used."""
    history = history or TuningHistory()
    base = base or AcampConfig()
    names = list(PARAM_SPACE)
    lows = [PARAM_SPACE[n][0] for n in names]
    highs = [PARAM_SPACE[n][1] for n in names]

    def denorm(unit: Sequence[float]) -> AcampConfig:
        raw = [lo + min(1.0, max(0.0, u)) * (hi - lo) for u, lo, hi in zip(unit, lows, highs, strict=True)]
        return from_vector(raw, base)

    def norm(cfg: AcampConfig) -> list[float]:
        return [
            (getattr(cfg, n) - lo) / (hi - lo) if hi > lo else 0.5
            for n, lo, hi in zip(names, lows, highs, strict=True)
        ]

    x0 = norm(base)
    best_cfg, best_obj = base, math.inf

    try:
        import cma

        es = cma.CMAEvolutionStrategy(
            x0,
            sigma0,
            {
                "popsize": population,
                "bounds": [0.0, 1.0],
                "seed": seed + 1,  # cma rejects seed=0 as "use a random one"
                "verbose": -9,
                "maxiter": generations,
            },
        )
        for gen in range(generations):
            candidates = es.ask()
            objectives = []
            for unit in candidates:
                cfg = denorm(unit)
                result = evaluate(cfg)
                history.record(gen, cfg, result)
                objectives.append(result.objective)
                if result.objective < best_obj:
                    best_obj, best_cfg = result.objective, cfg
                if on_generation is not None:
                    on_generation(gen, cfg, result)
            # CMA-ES cannot consume `inf`; a gridlocked candidate is
            # mapped to a large finite value that still ranks last within
            # its own generation, preserving the ordering the optimizer
            # actually uses without poisoning its internal statistics.
            finite = [o for o in objectives if math.isfinite(o)]
            ceiling = (max(finite) * 10.0) if finite else 1e12
            es.tell(candidates, [o if math.isfinite(o) else ceiling for o in objectives])
        return best_cfg, history
    except ImportError:
        pass

    # --- fallback: (mu, lambda)-ES, no covariance adaptation ---
    import random

    rng = random.Random(seed)
    mean = list(x0)
    sigma = sigma0
    mu = max(1, population // 2)
    for gen in range(generations):
        scored: list[tuple[float, list[float], AcampConfig]] = []
        for _ in range(population):
            unit = [min(1.0, max(0.0, m + rng.gauss(0.0, sigma))) for m in mean]
            cfg = denorm(unit)
            result = evaluate(cfg)
            history.record(gen, cfg, result)
            scored.append((result.objective, unit, cfg))
            if result.objective < best_obj:
                best_obj, best_cfg = result.objective, cfg
            if on_generation is not None:
                on_generation(gen, cfg, result)
        scored.sort(key=lambda t: t[0])
        elites = [u for _, u, _ in scored[:mu]]
        mean = [sum(e[i] for e in elites) / len(elites) for i in range(len(mean))]
        sigma *= 0.85  # geometric cooling -- explore early, refine late
    return best_cfg, history


def save_config(cfg: AcampConfig, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({name: getattr(cfg, name) for name in PARAM_SPACE}, indent=2, sort_keys=True)
    )


def load_config(path: str | Path, base: AcampConfig | None = None) -> AcampConfig:
    """Load a tuned config. Unknown keys are ignored and missing ones keep
    their default, so a config saved before a parameter was added to
    `PARAM_SPACE` still loads -- with the new parameter at its default,
    which is the correct reading of "this file predates that knob"."""
    payload = json.loads(Path(path).read_text())
    base = base or AcampConfig()
    known = {k: v for k, v in payload.items() if k in PARAM_SPACE}
    for name in _INTEGER_PARAMS & known.keys():
        known[name] = int(round(known[name]))
    return replace(base, **known)  # type: ignore[arg-type]
