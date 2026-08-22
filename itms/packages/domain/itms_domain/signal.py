"""Safety-kernel domain types [build guide §3.3, ARCH §2.2]. Pure value objects
-- no I/O, no clock reads, no bus/DB imports. This is what makes
`control/safety/interlocks.py` and its property tests possible: the same
plain data can be constructed by a real cabinet adapter, a strategy, a test
generator, or a Hypothesis strategy, and checked the same way in all four.

M2 scope note: junction geometry here (movements, conflict matrices, ring
order) is modeled generically -- a movement is just a string id, a phase is
just the set of movements it makes green -- rather than mapped onto the
actual 7 signal-controlled junctions in the Vijayawada corridor network.
That mapping (SUMO tlLogic phase strings <-> these types) is real work
deferred to whichever milestone first drives a live junction through this
kernel (M3's baseline strategies are the natural place); M2's job is the
kernel itself, correct and property-tested against synthetic junctions of
any shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Violation:
    """One interlock failure. `rule` is the invariant it violates (I1-I7, one
    rule can be raised by more than one predicate), `message` is human-
    readable detail for logs/alarms, `movements` names what's implicated."""

    rule: str
    message: str
    movements: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Phase:
    """A named set of movements that are simultaneously green. `is_pedestrian`
    marks a phase that serves a walk signal -- I4 only applies to these."""

    id: str
    green_movements: frozenset[str]
    is_pedestrian: bool = False


@dataclass(frozen=True)
class PlanStep:
    """One commitment in a SignalPlan: hold `phase_id` green for `green_s`,
    then (if the plan continues) clear for `yellow_s` + `all_red_s` before
    the next step's green starts. Clearance lives on the step that's ending,
    not the one starting -- it's what that green owes the movements it's
    about to stop protecting."""

    phase_id: str
    green_s: float
    yellow_s: float = 0.0
    all_red_s: float = 0.0


@dataclass(frozen=True)
class SignalPlan:
    """A proposal for one intersection. `source` names which arbitration-ladder
    rung produced it [ARCH §2.2] -- interlocks.check() doesn't care, but the
    signal_controller arbiter does (e.g. preempt_budget_ok only applies real
    teeth to `source == "corridor_preemption"`).

    Convention: `steps[0]` describes what happens to the junction's *current*
    live phase (continue it, or end it with proper clearance) before any
    later step's phase begins. A plan whose first step names a different
    phase from the context's `current_phase_id` is proposing an
    instantaneous change, and control/safety/interlocks.py's
    `min_green_satisfied` will reject it unless the context shows the
    current phase already served its minimum."""

    intersection_id: str
    steps: tuple[PlanStep, ...]
    source: str = "fixed_time"


@dataclass(frozen=True)
class JunctionContext:
    """Everything about a junction's current situation that the interlocks
    need but a SignalPlan doesn't carry itself -- the "world state" a
    proposal is being checked against.

    `wait_times_s` / `has_demand`: per movement. A movement only counts
    against I5 (max wait) while it actually has demand -- an empty approach
    can wait indefinitely without that being a safety problem.

    `ped_phase_in_progress` / `ped_phase_elapsed_s`: at most one pedestrian
    phase can be "in progress" at a time by construction (one ring position
    is active). `None` means no walk signal is currently mid-cycle.
    """

    intersection_id: str
    current_phase_id: str
    current_phase_elapsed_s: float
    wait_times_s: Mapping[str, float] = field(default_factory=dict)
    has_demand: Mapping[str, bool] = field(default_factory=dict)
    preempt_seconds_last_hour: float = 0.0
    faulted_phases: frozenset[str] = frozenset()
    ped_phase_in_progress: str | None = None
    ped_phase_elapsed_s: float = 0.0


@dataclass(frozen=True)
class Tier0Config:
    """Interlock parameters for one intersection [build guide §3.9 -- the
    Tier-0 rows: min_green_s, yellow_s/all_red_s, max_wait_s, conflict
    matrix, max_preempt_s]. Production governance for these (dual control,
    staged rollout, `safety_config.parameter` [ARCH §2.2, §5.2]) is real but
    out of scope here -- there's no operator/auth service to approve changes
    against yet (that lands with dispatch, M6/M7, same boundary noted in
    api-service's M1 docstring). M2 loads this as a plain, versionless
    config; C7 ("bad Tier-0 config value rejected, last-known-good
    retained") is implemented as this type's own validation, not the dual-
    control workflow.
    """

    intersection_id: str
    phases: Mapping[str, Phase]
    ring_order: tuple[str, ...]
    conflict_matrix: Mapping[str, frozenset[str]]
    min_green_s: Mapping[str, float]
    max_green_s: Mapping[str, float]
    yellow_s: float
    all_red_s: float
    ped_walk_s: Mapping[str, float] = field(default_factory=dict)
    ped_clearance_s: Mapping[str, float] = field(default_factory=dict)
    max_wait_s: float = 120.0
    max_preempt_s_per_hour: float = 300.0

    def validate(self) -> list[str]:
        """C7: "bad Tier-0 config value rejected at load, last-known-good
        retained". Returns problems found; the loader (not this method)
        decides what "retain last-known-good" means for its call site."""
        problems = []
        if self.yellow_s <= 0:
            problems.append(f"yellow_s must be > 0, got {self.yellow_s}")
        if self.all_red_s < 0:
            problems.append(f"all_red_s must be >= 0, got {self.all_red_s}")
        if not self.ring_order:
            problems.append("ring_order must not be empty")
        for phase_id in self.ring_order:
            if phase_id not in self.phases:
                problems.append(f"ring_order references unknown phase {phase_id!r}")
        for phase_id, phase in self.phases.items():
            if phase_id != phase.id:
                problems.append(f"phases key {phase_id!r} != Phase.id {phase.id!r}")
            if self.min_green_s.get(phase_id, 0) <= 0:
                problems.append(f"min_green_s[{phase_id!r}] must be > 0")
            max_g = self.max_green_s.get(phase_id)
            if max_g is not None and max_g < self.min_green_s.get(phase_id, 0):
                problems.append(f"max_green_s[{phase_id!r}] < min_green_s[{phase_id!r}]")
            if phase.is_pedestrian and phase_id not in self.ped_walk_s:
                problems.append(f"pedestrian phase {phase_id!r} missing ped_walk_s entry")
        for a, conflicts in self.conflict_matrix.items():
            for b in conflicts:
                if a not in self.conflict_matrix.get(b, frozenset()):
                    problems.append(f"conflict_matrix not symmetric for ({a!r}, {b!r})")
        return problems
