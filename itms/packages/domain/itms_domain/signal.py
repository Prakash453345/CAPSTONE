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
    marks a phase that serves a walk signal -- I4 only applies to these.

    `protected_movements` is the subset of `green_movements` that I1
    ("no two conflicting movements simultaneously green") actually checks
    against each other. Defaults to all of `green_movements` -- correct for
    every synthetic/hand-built junction (every M2 test config). Real
    SUMO-derived junctions can have permissive/yield movements (SUMO's
    lowercase 'g' -- e.g. a free/permitted turn) that are deliberately
    excluded here: SUMO enforces a dynamic yield check for those at
    runtime, independent of phase design, so they're already safe by a
    mechanism I1 doesn't need to duplicate. See
    `scenarios/networks/vijayawada/extract_tier0_config.py` for where a
    real junction's 'G' vs 'g' distinction gets translated into this
    field."""

    id: str
    green_movements: frozenset[str]
    is_pedestrian: bool = False
    protected_movements: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.protected_movements is None:
            object.__setattr__(self, "protected_movements", self.green_movements)


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


BLOCKER_UNKNOWN = "?"
"""`JunctionContext.blocked_by` value: a vehicle waits inside the junction
ahead of this lane, movement not known."""


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

    `queue_pcu` / `receiving_occupancy` / `confidence`: added for M4's
    CA-MP strategy [build guide §3.4/§3.8] -- per movement, the PCU-
    weighted queue `q_l`, the receiving link's occupancy `ρ_m` (used by
    CA-MP's blocking/gating term), and the state estimate's confidence
    `c_l` (drives the degradation ladder, §3.8). All default to an empty
    mapping, same additive-not-a-behaviour-change pattern as
    `has_demand`/`wait_times_s` before them: `fixed_time`/`webster`/
    `semi_actuated`/`coordinated_actuated` never read these fields, so
    every existing caller is unaffected. A movement absent from
    `confidence` is treated as fully confident (`c_l = 1.0`) by CA-MP --
    correct for this build, where every movement's state still comes
    from SUMO ground truth (no sensor-equivalence degradation layer
    exists before M8) rather than a real vision pipeline that could
    actually be less than fully confident.

    `receiving_queue_pcu` / `approaching_pcu`: added for M5's A-CA-MP
    strategy, and both exist to close gaps M4's own module docstring
    named as open.

    `receiving_queue_pcu[m]` is the PCU-weighted *stopped* queue on the
    downstream lane movement `m` discharges into -- the same physical
    quantity `queue_pcu` measures, pointed one link forward. M4 had no
    source for this ("that would need a lane -> downstream-lane map this
    build doesn't have", `camp.py`'s docstring) and worked around its
    absence by reusing `queue_pcu[m]` inside its own blocking term, which
    is what makes M4's `P_flow`/`P_block` pair cancel exactly at zero
    receiving occupancy. The map in fact already existed --
    `link_lanes.link_to_receiving_lane_map()`, which
    `receiving_occupancy` is itself sampled through -- so this is the
    same lane, measured for queue instead of only occupancy. With it,
    pressure can be the textbook upstream-minus-downstream difference
    [Varaiya 2013] rather than a scaled self-difference.

    `approaching_pcu[m]` is the PCU-weighted count of vehicles *moving*
    on `m`'s own approach lane whose time-to-stopline falls inside the
    controller's decision horizon -- the observable half of M4's deferred
    `q̂_l = q_l + ∫ â_l dτ` arrival augmentation. M4 scoped that term to
    M5's Layer-2 projected-outflow exchange (a neighbour *publishing* its
    predicted departures) and therefore left `q̂_l = q_l`; but the portion
    of that integral contributed by vehicles already on this junction's
    own approach needs no inter-junction exchange at all, only a look at
    the lane the junction can already see. Layer 2's exchange remains the
    right source for arrivals still upstream of the neighbour; this field
    is the strictly-local part that never needed to wait for it.

    Both default empty, the same additive pattern `queue_pcu`/
    `receiving_occupancy` followed: no M2/M3/M4 strategy reads either, so
    `fixed_time`/`webster`/`semi_actuated`/`coordinated_actuated`/`camp`
    are all bit-for-bit unaffected by their existence.
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
    queue_pcu: Mapping[str, float] = field(default_factory=dict)
    receiving_occupancy: Mapping[str, float] = field(default_factory=dict)
    confidence: Mapping[str, float] = field(default_factory=dict)
    receiving_queue_pcu: Mapping[str, float] = field(default_factory=dict)
    approaching_pcu: Mapping[str, float] = field(default_factory=dict)
    blocked_by: Mapping[str, str] = field(default_factory=dict)
    """Head-of-line blocking: `{movement: the movement of the vehicle blocking
    its lane}`. A movement appears here when the vehicle at the front of its
    approach lane is stopped directly behind a vehicle that is waiting inside
    the junction (a turner yielding to oncoming traffic); the value is that
    waiting vehicle's movement, or `BLOCKER_UNKNOWN` when the sensor sees
    where the vehicle stands but not which way it is going (a camera: on a
    shared lane the turn's path and the through path are centimetres apart
    where the turner waits). Every movement sharing the lane gets the same
    entry. Empty (the default) when nothing is blocked or nothing measures
    it; only `strategies/hol_camp.py` reads it."""


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

    `sat_flow_pcu_s` (`s_lm` [§3.9]): per-movement saturation flow, PCU/s,
    condition-adjusted -- Tier-1 (measured, hot-reloadable), not itself an
    interlock parameter, but kept alongside them here since it's still a
    per-junction physical property of the approach, the same home as
    `min_green_s`/`max_green_s`. Defaults to empty; only CA-MP (M4) reads
    it -- every M2/M3 strategy is unaffected by its absence.
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
    sat_flow_pcu_s: Mapping[str, float] = field(default_factory=dict)
    alternates: Mapping[str, str] = field(default_factory=dict)
    """`{phase id: the ring phase it stands in for}`: configured phases that
    are not ring members but may be commanded in place of one. An alternate
    is its ring phase with some *protected* movements taken away and nothing
    else changed (`strategies/hol.py`): every movement it shows, it shows as
    the ring phase does, and it stops no permissive movement of it --
    `validate` checks both. So it contains no pair of greens the ring phase
    does not, and everything the interlocks check about a phase (conflicts,
    clearance, green bounds) is checked for it as for any other. Empty for
    every junction that has none."""

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
        problems.extend(self.alternate_problems())
        return problems

    def alternate_problems(self, only: str | None = None) -> list[str]:
        """What is wrong with this junction's alternates (`only`: with that
        one), empty when nothing is. These are the properties that make an
        alternate as safe as the ring phase it stands in for, so a junction
        with any of them is not run (`control/runner.py`) and a plan that
        steps into such an alternate is refused (`interlocks.transition_legal`):

        - it is a configured phase, standing in for a ring phase, with a
          minimum green of its own;
        - it shows nothing the ring phase does not, and shows each movement
          the same way (protected stays protected, permissive permissive) --
          so no pair of greens exists in it that the ring phase lacks;
        - it stops at least one movement, and only protected ones -- stopping
          a yielding movement while the stream it yields to may run on is
          the yellow trap;
        - it keeps a protected movement (a phase with none is read as "all
          protected" by the cabinet and the kernel);
        - its signal state is its own (the cabinet tells phases apart by
          their state);
        - the junction has an all-red (leaving an alternate restarts what
          it stopped, and that must start into an empty junction)."""
        problems: list[str] = []
        for alt, base in self.alternates.items():
            if only is not None and alt != only:
                continue
            if alt not in self.phases:
                problems.append(f"alternate {alt!r} is not a configured phase")
                continue
            if base not in self.ring_order or base not in self.phases:
                problems.append(f"alternate {alt!r} stands in for {base!r}, not a ring phase")
                continue
            a, b = self.phases[alt], self.phases[base]
            a_protected = a.protected_movements or frozenset()
            b_protected = b.protected_movements or frozenset()
            if self.min_green_s.get(alt, 0) <= 0:
                problems.append(f"alternate {alt!r} has no minimum green")
            if self.all_red_s <= 0:
                problems.append(f"alternate {alt!r} needs an all-red interval at the junction")
            if not a.green_movements <= b.green_movements:
                problems.append(f"alternate {alt!r} serves movements {base!r} does not")
                continue
            stopped = b.green_movements - a.green_movements
            if not stopped:
                problems.append(f"alternate {alt!r} stops nothing of {base!r}")
            if a_protected != b_protected & a.green_movements:
                problems.append(f"alternate {alt!r} shows a movement differently from {base!r}")
            if not a_protected:
                problems.append(f"alternate {alt!r} has no protected movement")
            if not stopped <= b_protected:
                problems.append(f"alternate {alt!r} stops a permissive movement of {base!r}")
            for pid, p in self.phases.items():
                if pid != alt and p.green_movements == a.green_movements and (
                        p.protected_movements or frozenset()) == a_protected:
                    problems.append(f"alternate {alt!r} shows the same signal state as {pid!r}")
        return problems
