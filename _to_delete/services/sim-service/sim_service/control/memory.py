"""Cross-run demand memory -- the `q_hist` M4's degradation ladder named
but had no source for.

**What this is, stated precisely, because the framing is the whole
methodological claim.** `camp.py`'s `select_mode` implements §3.8's three
rungs, but only one of them ("camp_full") was ever behaviourally real:

    "CAMP_BLENDED" needs a historical time-of-day queue profile
    (`q_hist`) and "profile-actuated" needs a `signal_plan_library`;
    neither data source exists before real state-estimation
    infrastructure does.

That was true of the *sensor* half of the problem and false of the
*history* half. A historical profile does not need a vision pipeline to
exist -- it needs the controller to have run before and written down what
it saw. This module is that written-down record.

**One seed is one day.** The corridor's demand files
(`build_demand_levels.sh`) define a fixed time-of-day demand *shape*;
SUMO's `--seed` chooses one stochastic realization of it. Two seeds are
therefore exactly analogous to two Tuesdays at the same junction: the
same underlying pattern (school run, evening peak), a different
particular set of vehicles. That analogy is what makes this a legitimate
"train on past experience" setup rather than a self-fulfilling one, and
it comes with an obligation this module's callers must honour: a profile
learned on seeds A..J may only ever be *evaluated* on seeds outside that
set. `scripts/train_acamp.py` and `scripts/m5_gate_comparison.py` keep
disjoint seed sets for exactly this reason. Reporting a gate number from
a profile that had already seen that seed's own realization would be
testing on the training set, and the resulting figure would be
meaningless.

**What it stores, and why an EWMA rather than a mean.** Per
`(intersection_id, movement, time-of-day bin)`: the PCU-weighted stopped
queue and the inbound-platoon count, each as an exponentially-weighted
moving average across runs. A plain mean over all history weights a
run from a year ago identically to yesterday's; real demand drifts (a new
flyover opens, a school changes its hours) and a controller whose memory
cannot forget is worse than one with none, because it is confidently
wrong rather than merely ignorant. `decay` is the forgetting factor:
1.0 would be a plain running mean, 0.0 would keep only the newest run.

**What it deliberately does not do:** predict. `profile()` returns what
this junction has historically looked like at this time of day, not a
forecast of what it will look like now. The consumer
(`acamp.AdaptiveCamp`) uses it only where live state is missing or
low-confidence -- it is a *fallback prior*, not a second opinion that
gets averaged into a perfectly good live measurement. That restriction is
what keeps the degradation ladder a ladder: rungs are for when the rung
above has failed, not a blend to be applied unconditionally.

Pure Python + JSON, no DB: this is Phase-1 sim infrastructure, and a
`historical_profile` table in the real Postgres schema [ARCH §5] is where
this lives in production. The shape here is deliberately table-like
(composite key, two measures, a sample count) so that migration is a
schema translation, not a redesign.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# Width of one time-of-day bin, seconds. 15 minutes is the standard
# traffic-engineering aggregation interval (it is what a peak-hour factor
# is computed over, and what every count survey this corridor's own
# `measure_flows.py` mimics reports in), so a profile binned this way can
# be compared against real survey data without re-binning.
_BIN_WIDTH_S = 900.0

# Forgetting factor for the across-run EWMA. 0.7 keeps roughly the last
# three or four runs at meaningful weight (0.7^4 ~ 0.24) -- enough to
# average out one seed's noise, short enough to track a genuine demand
# shift within a handful of days rather than a season.
_DECAY = 0.7

# Below this many contributing runs a bin's profile is reported as
# unavailable rather than as a low-confidence number. One run's queue at
# one junction at one 15-minute bin is a single sample of a stochastic
# process; handing it to a controller as "what usually happens" would be
# the exact overconfidence this module's own docstring warns about.
_MIN_RUNS_FOR_PROFILE = 2


def _bin_of(sim_time_s: float, *, bin_width_s: float = _BIN_WIDTH_S) -> int:
    return int(sim_time_s // bin_width_s)


@dataclass
class _BinStats:
    """One `(junction, movement, bin)` cell. `runs` counts *runs* that
    contributed, not ticks -- a 900s bin sampled every second would
    otherwise report 900 "samples" of what is really one day's
    observation, and any confidence derived from that count would be
    inflated by the sampling rate rather than by evidence."""

    queue_pcu: float = 0.0
    approaching_pcu: float = 0.0
    runs: int = 0
    # Within-run accumulation, reset by `end_run`. Kept separate from the
    # committed EWMA so a run in progress can never contaminate the
    # history it is about to be folded into -- `profile()` during a run
    # reads only what previous runs committed.
    _live_queue_sum: float = 0.0
    _live_approaching_sum: float = 0.0
    _live_ticks: int = 0

    def observe(self, queue_pcu: float, approaching_pcu: float) -> None:
        self._live_queue_sum += queue_pcu
        self._live_approaching_sum += approaching_pcu
        self._live_ticks += 1

    def commit(self, decay: float) -> None:
        """Fold this run's within-bin mean into the across-run EWMA. A bin
        this run never visited (`_live_ticks == 0`) is left completely
        untouched rather than folded in as a zero: "no vehicle was
        observed here" and "this bin was never sampled" are different
        facts, and averaging the second in as the first would drag every
        profile toward zero in proportion to how often the run ended
        early."""
        if self._live_ticks == 0:
            return
        run_queue = self._live_queue_sum / self._live_ticks
        run_approaching = self._live_approaching_sum / self._live_ticks
        if self.runs == 0:
            self.queue_pcu = run_queue
            self.approaching_pcu = run_approaching
        else:
            self.queue_pcu = decay * self.queue_pcu + (1.0 - decay) * run_queue
            self.approaching_pcu = (
                decay * self.approaching_pcu + (1.0 - decay) * run_approaching
            )
        self.runs += 1
        self._live_queue_sum = 0.0
        self._live_approaching_sum = 0.0
        self._live_ticks = 0


@dataclass
class DemandMemory:
    """The whole corridor's historical profile. One instance per
    controller process; `load`/`save` move it across runs.

    Thread-safety is not addressed and does not need to be in Phase 1:
    `runner.py` drives every junction from one loop on one thread. A real
    deployment writing this from several controller processes would need
    the Postgres row-level locking this JSON file has no equivalent of --
    named here so the gap is a known one rather than an assumption that
    silently breaks at deployment."""

    bin_width_s: float = _BIN_WIDTH_S
    decay: float = _DECAY
    min_runs: int = _MIN_RUNS_FOR_PROFILE
    _cells: dict[str, _BinStats] = field(default_factory=dict)

    @staticmethod
    def _key(intersection_id: str, movement: str, bin_index: int) -> str:
        return f"{intersection_id}\x1f{movement}\x1f{bin_index}"

    def observe_tick(
        self,
        intersection_id: str,
        sim_time_s: float,
        queue_pcu: Mapping[str, float],
        approaching_pcu: Mapping[str, float],
    ) -> None:
        """Record one tick. Cheap enough to call every tick (two float adds
        per movement); the runner does exactly that rather than
        subsampling, since a subsample interval would be one more constant
        to justify and the cost it saves is not measurable against a TraCI
        step."""
        bin_index = _bin_of(sim_time_s, bin_width_s=self.bin_width_s)
        for movement, q in queue_pcu.items():
            key = self._key(intersection_id, movement, bin_index)
            cell = self._cells.get(key)
            if cell is None:
                cell = self._cells[key] = _BinStats()
            cell.observe(q, approaching_pcu.get(movement, 0.0))

    def end_run(self) -> None:
        """Commit every bin this run touched into the across-run EWMA.
        Called once when a scenario finishes -- *not* per bin boundary, so
        a run that ends mid-bin still contributes that partial bin's mean
        rather than discarding it."""
        for cell in self._cells.values():
            cell.commit(self.decay)

    def profile(
        self, intersection_id: str, movement: str, sim_time_s: float
    ) -> tuple[float, float] | None:
        """`(queue_pcu, approaching_pcu)` this junction historically shows
        for `movement` at this time of day, or `None` when too few runs
        have contributed to say. `None` is a real answer the caller must
        handle, not an error -- a controller with no history is exactly
        the cold-start case, and it should fall back to live state alone
        rather than to a fabricated zero."""
        bin_index = _bin_of(sim_time_s, bin_width_s=self.bin_width_s)
        cell = self._cells.get(self._key(intersection_id, movement, bin_index))
        if cell is None or cell.runs < self.min_runs:
            return None
        return cell.queue_pcu, cell.approaching_pcu

    def coverage(self) -> tuple[int, int]:
        """`(cells with a usable profile, cells total)` -- what a run can
        report so a benchmark never has to guess whether the memory it was
        handed was actually populated. A gate result quoting "with demand
        memory" while coverage was 0/N would be a claim about code that
        never executed."""
        usable = sum(1 for c in self._cells.values() if c.runs >= self.min_runs)
        return usable, len(self._cells)

    # ---- persistence -------------------------------------------------

    def save(self, path: str | Path) -> None:
        payload = {
            "bin_width_s": self.bin_width_s,
            "decay": self.decay,
            "min_runs": self.min_runs,
            "cells": {
                key: {
                    "queue_pcu": cell.queue_pcu,
                    "approaching_pcu": cell.approaching_pcu,
                    "runs": cell.runs,
                }
                for key, cell in self._cells.items()
                if cell.runs > 0
            },
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a run interrupted mid-save must not leave a
        # truncated profile that the next run would load as real history.
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(target)

    @classmethod
    def load(cls, path: str | Path) -> DemandMemory:
        """Load a saved profile, or return an empty one if the file does
        not exist -- cold start is the normal first-run case, not a
        failure."""
        source = Path(path)
        if not source.exists():
            return cls()
        payload = json.loads(source.read_text())
        memory = cls(
            bin_width_s=payload.get("bin_width_s", _BIN_WIDTH_S),
            decay=payload.get("decay", _DECAY),
            min_runs=payload.get("min_runs", _MIN_RUNS_FOR_PROFILE),
        )
        for key, cell in payload.get("cells", {}).items():
            memory._cells[key] = _BinStats(
                queue_pcu=cell["queue_pcu"],
                approaching_pcu=cell["approaching_pcu"],
                runs=cell["runs"],
            )
        return memory


def blend(live: float, historical: float | None, confidence: float) -> float:
    """§3.8's "camp_blended" rung, made real: trust live state in
    proportion to its own confidence, fall back on history for the rest.

    `historical is None` (cold start, or a bin with too few runs) returns
    `live` untouched -- with nothing to blend toward, a partially-trusted
    live reading is still strictly better than shrinking it toward an
    invented zero, which is what a `historical or 0.0` default would
    silently do.

    `confidence` is clamped rather than asserted in range: it arrives from
    `JunctionContext.confidence`, which in a real deployment is a vision
    pipeline's own output, and a control path is the wrong place to
    discover an upstream service emitted 1.02. Out-of-range values are
    clamped and used; the sensor's own health monitoring is where that
    belongs as an alarm."""
    if historical is None:
        return live
    c = min(1.0, max(0.0, confidence))
    return c * live + (1.0 - c) * historical


def sublinear_hold_bias(scale: float, kappa: float, alpha: float) -> float:
    """LESCMP's switching curve `F(x)`, the property that matters most
    here [Xu et al., Transp. Res. Part C 137 (2022), Theorem 3].

    Returns the extra pressure advantage a *challenger* phase must show
    before it is worth paying a clearance interval to switch to it, given
    `scale` -- the junction's current total pressure magnitude.

    **Why this shape, and why it is the direct fix for M4's own worst
    bug.** `camp._switch` prices switching as a per-phase constant. A
    constant is `O(1)` while pressure differences scale with real queue
    size, so there is always some demand level below which the constant
    dominates every genuine pressure comparison -- and PROGRESS.md records
    exactly that outcome, measured: the switch cost came out 61x typical
    flow pressure at light demand, 22x at medium, 5x at heavy, and 100% of
    phase changes across 44,000 extend-eligible ticks were `max_green_s`
    timeouts rather than a pressure decision. The controller was
    functionally fixed-time at every demand level tested.

    Requiring `0 < alpha < 1` makes `F(x)/x -> 0` as `x -> inf`, which is
    the sublinearity condition Theorem 3's Lyapunov drift argument needs
    for throughput-optimality to survive the introduction of a switching
    penalty at all. It also rules out M4's failure by construction rather
    than by tuning: however large `kappa` is, the hold bias is eventually
    negligible against the pressure differences it is compared to, so no
    parameter setting -- learned or hand-picked -- can reproduce a
    controller that structurally refuses to switch under load. `alpha = 0`
    is precisely M4's constant, and is excluded; `alpha = 1` would scale
    with pressure exactly and never become negligible, and is excluded
    too. `tuning.py` searches strictly inside the open interval for this
    reason, and this function enforces it rather than trusting it.

    At `scale = 0` (a genuinely empty junction) the bias is 0: nothing is
    waiting anywhere, so there is no reason to resist cycling onward, and
    a nonzero floor here would reintroduce M4's "never leaves the current
    phase at light demand" behaviour in miniature."""
    if not 0.0 < alpha < 1.0:
        raise ValueError(
            f"alpha must be strictly inside (0, 1) for the sublinearity "
            f"guarantee -- got {alpha}. alpha=0 reproduces M4's constant "
            f"switching cost; alpha=1 scales with pressure and never "
            f"becomes negligible."
        )
    if scale <= 0.0:
        return 0.0
    return kappa * math.pow(scale, alpha)
