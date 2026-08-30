"""Learning from prediction error -- the controller checking its own
model of the road against what the road actually did.

**Why this is a different thing from the memories already here.**
`memory.DemandMemory` records what the corridor *looked like* and
`tuning.py` fits parameters to an aggregate outcome offline. Neither is
error correction: nothing in either compares a prediction to its result.
Up to this module, A-CA-MP made three implicit predictions on every
decision and checked none of them:

    "this phase will discharge s_m x green PCU"   <- sat_flow_pcu_s
    "this approach is empty, safe to skip"        <- _skippable
    "this platoon arrives within the horizon"     <- approaching_pcu

All three are observable a few seconds later. This module closes the loop
on the first and third; the second is noted at the bottom as the one
genuinely harder case.

**Why saturation flow is the one worth closing first.** `s_m` multiplies
*every* term in `𝒫(p)` -- flow, blocking, fairness, and the switching
test's own scale -- so an error in it is an error in everything. And it
is the project's most confidently-held wrong number:
`measure_saturation_flow.py` measures it once, offline, on an isolated
empty approach with an artificially heavy backlog. That is the textbook
definition of saturation flow and the right way to measure it, but it
describes a road that does not exist during operation: no cross traffic,
no weather, no blocking, no unusual vehicle mix. It is then trusted
forever. Five of this corridor's 73 movements never got a clean reading
at all and still sit on a 0.5 placeholder against a measured corridor
mean of 0.400 -- 25% high, permanently, on a term that scales the whole
pressure function.

Every green is a natural experiment that could correct it, and none of
them were being used.

**The identification problem, which is the whole difficulty.** The naive
estimator -- observed discharge divided by green time -- is badly biased,
and biased in one direction. If a movement's queue clears after 8s of a
20s green, the remaining 12s discharge only whatever trickles in, so the
average rate over the green is far below saturation flow. Applied
naively, the estimator would drag every `s_m` downward at exactly the
junctions that are performing *well*, and a controller that concludes its
uncongested approaches have low capacity will then over-serve them. That
failure would look like learning and be worse than not learning.

Saturation flow is by definition the discharge rate of a queue that has
not run out. So an observation only counts when the queue was still
non-empty at the end of the green -- the same condition
`measure_saturation_flow.py` engineers deliberately by pre-loading a
backlog, here waited for rather than manufactured. Most greens at light
demand contribute nothing, which is correct: they contain no information
about capacity. `saturated_samples` is reported alongside every learned
value so a reader can tell a well-evidenced correction from one resting
on two observations.

**Bounds, and why they are not tuning.** A learned `s_m` is clamped to a
multiplicative band around its offline-calibrated value. This is not a
hedge against the estimator being wrong -- it is a statement that the
offline measurement is real evidence, taken under controlled conditions,
and that operational data should refine it rather than replace it. A
movement whose learned value wants to sit 3x above its measured
saturation flow has an observation problem (a detector fault, a
mis-mapped lane), not a capacity discovery, and the band turns that into
a visible clamp instead of a silent corruption of the pressure function.

**Safety.** Nothing here can reach an interlock. `sat_flow_pcu_s` is a
Tier-1 measured quantity, explicitly not one of `Tier0Config`'s interlock
parameters -- min-green, clearance intervals, the conflict matrix and the
max-wait bound are untouched and unreachable from this module. A learned
value that was wildly wrong would produce a *bad* plan, and
`interlocks.check` would still reject it before it reached a cabinet,
exactly as it does for any other bad plan.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# EWMA step for the saturation-flow correction. Deliberately small: each
# observation is one green at one movement, a handful of vehicles, and
# real capacity drifts on the timescale of weather and season rather than
# minutes. 0.10 gives roughly a 10-green memory, so a single anomalous
# discharge moves the estimate by a tenth of its own error and a genuine
# shift is tracked within a few dozen greens.
_SAT_FLOW_ALPHA = 0.10

# Multiplicative band around the offline-calibrated value. See the module
# docstring: this encodes "operational data refines a controlled
# measurement" rather than "the estimator might be wrong".
_SAT_FLOW_MIN_FACTOR = 0.5
_SAT_FLOW_MAX_FACTOR = 2.0

# A green must discharge at least this much PCU before it is used as a
# capacity observation. One or two vehicles crossing tells you almost
# nothing about a saturation rate and everything about the particular
# driver; this is the same reason `measure_saturation_flow.py` discards
# its own first few crossings as the start-up wave.
_MIN_SAMPLE_PCU = 3.0

# And it must have been green long enough for the start-up wave to have
# passed, or the measured rate is start-up lost time rather than
# saturation flow.
_MIN_EFFECTIVE_GREEN_S = 5.0

# EWMA step for arrival reliability -- larger than the saturation-flow
# step because the quantity is a ratio in [0,1] with far more samples
# (every tick contributes a cohort, not every green) and no controlled
# offline measurement to defer to.
_ARRIVAL_ALPHA = 0.05


@dataclass
class MovementModel:
    """What has been learned about one movement, and how well evidenced
    it is."""

    baseline_sat_flow: float
    """The offline-calibrated value (or the placeholder, for the five
    movements that never got one). Kept so the band is anchored to
    measured evidence rather than to wherever the estimate has drifted."""

    sat_flow: float = 0.0
    saturated_samples: int = 0
    """Greens that ended with the queue still non-empty -- the only ones
    that carry capacity information. Reported so a reader can tell a
    well-evidenced correction from one resting on two observations."""

    rejected_samples: int = 0
    """Greens observed but not used. Tracked because the *ratio* is
    diagnostic -- a movement that never produces a saturated green is one
    this mechanism can say nothing about, and silence about that would
    look like agreement with the offline number."""

    rejected_unsaturated: int = 0
    rejected_too_small: int = 0
    rejected_too_short: int = 0
    """Rejections split by cause, because the aggregate cannot
    distinguish "this approach is never busy enough to measure" from
    "the thresholds are set wrong". The first is a fact about the
    corridor and the second is a bug, and a single counter reads
    identically for both."""

    arrival_reliability: float = 1.0
    """Fraction of the traffic counted as "approaching" that actually
    arrived within the horizon. Below 1.0 where vehicles turn off, change
    lanes, or are held up before reaching the stop line -- in which case
    `approaching_pcu` was overstating this movement's claim on green."""

    arrival_samples: int = 0
    last_residual: float = 0.0
    """Most recent `observed_rate - predicted_rate`. Instrumentation, not
    control -- it is what makes "is it actually learning, and in which
    direction" answerable from a run."""

    def __post_init__(self) -> None:
        if self.sat_flow <= 0.0:
            self.sat_flow = self.baseline_sat_flow


@dataclass
class OnlineCalibration:
    """The corridor's learned model, keyed by `(junction, movement)`.

    Persisted like `DemandMemory`, and for the same reason: capacity
    learned on Tuesday is still true on Wednesday, and a controller that
    forgets it every restart would spend its first hour every day
    re-deriving what it already knew.
    """

    alpha: float = _SAT_FLOW_ALPHA
    arrival_alpha: float = _ARRIVAL_ALPHA
    min_factor: float = _SAT_FLOW_MIN_FACTOR
    max_factor: float = _SAT_FLOW_MAX_FACTOR
    models: dict[str, MovementModel] = field(default_factory=dict)

    @staticmethod
    def _key(intersection_id: str, movement: str) -> str:
        return f"{intersection_id}\x1f{movement}"

    def _model(self, intersection_id: str, movement: str, baseline: float) -> MovementModel:
        key = self._key(intersection_id, movement)
        model = self.models.get(key)
        if model is None:
            model = self.models[key] = MovementModel(baseline_sat_flow=baseline)
        return model

    # ---- prediction 1: discharge rate ---------------------------------

    def observe_green(
        self,
        intersection_id: str,
        movement: str,
        *,
        baseline_sat_flow: float,
        discharged_pcu: float,
        effective_green_s: float,
        queue_remained: bool,
    ) -> float | None:
        """Fold one completed green into this movement's capacity
        estimate. Returns the residual `observed - predicted` when the
        observation was used, or `None` when it was rejected.

        `queue_remained` is the identification condition and the single
        most important argument: saturation flow is the discharge rate of
        a queue that has *not* run out, so a green whose queue cleared
        early measures how much traffic there was, not how fast the
        approach can serve it. Using those observations would drag every
        estimate down at precisely the movements that are keeping up. See
        the module docstring."""
        model = self._model(intersection_id, movement, baseline_sat_flow)
        if not queue_remained:
            model.rejected_samples += 1
            model.rejected_unsaturated += 1
            return None
        if effective_green_s < _MIN_EFFECTIVE_GREEN_S:
            model.rejected_samples += 1
            model.rejected_too_short += 1
            return None
        if discharged_pcu < _MIN_SAMPLE_PCU:
            model.rejected_samples += 1
            model.rejected_too_small += 1
            return None

        observed_rate = discharged_pcu / effective_green_s
        residual = observed_rate - model.sat_flow
        updated = model.sat_flow + self.alpha * residual
        model.sat_flow = min(
            model.baseline_sat_flow * self.max_factor,
            max(model.baseline_sat_flow * self.min_factor, updated),
        )
        model.saturated_samples += 1
        model.last_residual = residual
        return residual

    # ---- prediction 3: platoon arrival --------------------------------

    def observe_arrivals(
        self,
        intersection_id: str,
        movement: str,
        *,
        baseline_sat_flow: float,
        predicted_pcu: float,
        arrived_pcu: float,
    ) -> None:
        """Fold one arrival cohort's outcome into `arrival_reliability`.

        `approaching_pcu` counts vehicles whose time-to-stopline falls
        inside the horizon, which assumes they keep going and keep
        heading here. Some do not: they turn off, change lanes into
        another movement, or get held behind something. The fraction that
        genuinely arrive is a per-movement property of the geometry, and
        learning it is the difference between anticipation that helps and
        anticipation that inflates a phase's claim on green with traffic
        that was never coming."""
        if predicted_pcu <= 0.0:
            return
        model = self._model(intersection_id, movement, baseline_sat_flow)
        observed_ratio = min(1.0, arrived_pcu / predicted_pcu)
        model.arrival_reliability += self.arrival_alpha * (
            observed_ratio - model.arrival_reliability
        )
        model.arrival_samples += 1

    # ---- reading it back ----------------------------------------------

    def sat_flow_for(self, intersection_id: str, config_value: float, movement: str) -> float:
        """The learned capacity, or the config value where nothing has
        been learned. Falling back to the config rather than to a global
        mean is deliberate: an unobserved movement should behave exactly
        as it did before this module existed."""
        model = self.models.get(self._key(intersection_id, movement))
        return model.sat_flow if model and model.saturated_samples > 0 else config_value

    def arrival_reliability_for(self, intersection_id: str, movement: str) -> float:
        model = self.models.get(self._key(intersection_id, movement))
        return model.arrival_reliability if model and model.arrival_samples > 0 else 1.0

    def sat_flow_overrides(
        self, intersection_id: str, config: Mapping[str, float]
    ) -> dict[str, float]:
        """Every movement's effective saturation flow for one junction,
        ready to drop into a `Tier0Config` copy."""
        return {
            m: self.sat_flow_for(intersection_id, v, m) for m, v in config.items()
        }

    def report(self) -> dict:
        """What was learned, for a run to print or a gate to record.
        Includes the rejection ratio: a movement that never produced a
        saturated green is one this mechanism can say nothing about, and
        that silence must not read as agreement with the offline value."""
        learned = [m for m in self.models.values() if m.saturated_samples > 0]
        # The rejection breakdown is reported unconditionally, and
        # deliberately *before* the early return. An earlier version put
        # it only in the learned branch, which meant the diagnostics
        # disappeared in exactly the case they exist for: a run that
        # learned nothing is the one where "why not" is the question, and
        # a report that answers it with silence is worse than no report.
        base = {
            "movements_learned": len(learned),
            "movements_seen": len(self.models),
            "rejected_samples": sum(m.rejected_samples for m in self.models.values()),
            "rejected_unsaturated": sum(m.rejected_unsaturated for m in self.models.values()),
            "rejected_too_small": sum(m.rejected_too_small for m in self.models.values()),
            "rejected_too_short": sum(m.rejected_too_short for m in self.models.values()),
        }
        if not learned:
            return base
        deltas = [(m.sat_flow - m.baseline_sat_flow) / m.baseline_sat_flow for m in learned]
        return {
            **base,
            "saturated_samples": sum(m.saturated_samples for m in learned),
            "mean_relative_change": sum(deltas) / len(deltas),
            "max_relative_increase": max(deltas),
            "max_relative_decrease": min(deltas),
            "at_upper_bound": sum(
                1 for m in learned if m.sat_flow >= m.baseline_sat_flow * self.max_factor - 1e-9
            ),
            "at_lower_bound": sum(
                1 for m in learned if m.sat_flow <= m.baseline_sat_flow * self.min_factor + 1e-9
            ),
            "arrival_reliability_mean": (
                sum(m.arrival_reliability for m in self.models.values() if m.arrival_samples > 0)
                / max(1, sum(1 for m in self.models.values() if m.arrival_samples > 0))
            ),
        }

    # ---- persistence ---------------------------------------------------

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "alpha": self.alpha,
            "arrival_alpha": self.arrival_alpha,
            "min_factor": self.min_factor,
            "max_factor": self.max_factor,
            "models": {
                key: {
                    "baseline_sat_flow": m.baseline_sat_flow,
                    "sat_flow": m.sat_flow,
                    "saturated_samples": m.saturated_samples,
                    "rejected_samples": m.rejected_samples,
                    "rejected_unsaturated": m.rejected_unsaturated,
                    "rejected_too_small": m.rejected_too_small,
                    "rejected_too_short": m.rejected_too_short,
                    "arrival_reliability": m.arrival_reliability,
                    "arrival_samples": m.arrival_samples,
                }
                for key, m in self.models.items()
            },
        }
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(target)

    @classmethod
    def load(cls, path: str | Path) -> OnlineCalibration:
        source = Path(path)
        if not source.exists():
            return cls()
        payload = json.loads(source.read_text())
        cal = cls(
            alpha=payload.get("alpha", _SAT_FLOW_ALPHA),
            arrival_alpha=payload.get("arrival_alpha", _ARRIVAL_ALPHA),
            min_factor=payload.get("min_factor", _SAT_FLOW_MIN_FACTOR),
            max_factor=payload.get("max_factor", _SAT_FLOW_MAX_FACTOR),
        )
        for key, m in payload.get("models", {}).items():
            cal.models[key] = MovementModel(
                baseline_sat_flow=m["baseline_sat_flow"],
                sat_flow=m["sat_flow"],
                saturated_samples=m["saturated_samples"],
                rejected_samples=m.get("rejected_samples", 0),
                rejected_unsaturated=m.get("rejected_unsaturated", 0),
                rejected_too_small=m.get("rejected_too_small", 0),
                rejected_too_short=m.get("rejected_too_short", 0),
                arrival_reliability=m.get("arrival_reliability", 1.0),
                arrival_samples=m.get("arrival_samples", 0),
            )
        return cal


# The third prediction -- `_skippable`'s "this approach is empty, safe to
# pass over" -- is deliberately not closed here, and the reason is that it
# is the only one of the three without a clean residual. Discharge and
# arrival both have an observable counterfactual-free outcome: the traffic
# either crossed or it did not. A skip does not. Once the phase is passed
# over, what *would* have happened had it been served is unobservable, and
# the wait that accumulates afterwards is a consequence of every later
# decision too, not of the skip alone. Estimating it properly needs either
# a counterfactual model or deliberate randomized exploration -- serving
# skippable phases occasionally on purpose to measure the difference --
# and randomized exploration on a live signalized junction is a different
# proposition from passive observation, however well the safety kernel
# bounds it. Flagged as the harder case rather than approximated with a
# residual that does not mean what it appears to.
