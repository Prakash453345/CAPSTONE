"""Incident lifecycle state machine [build guide M6; ADR-006 human-in-the-loop
gate]. Pure value objects and a transition function -- no I/O, no clock reads,
no bus/DB imports, exactly like `signal.py`. Wall-clock times are passed in as
arguments (`at_ms`), never read here; `hashlib`/`json` are used only for pure
in-memory hashing of the audit chain.

The shape M6's anomaly stream drives an incident through:

    (detector raises)      -> CANDIDATE
    CANDIDATE --confirm-->     CONFIRMED     (an operator; -> IncidentDetected)
    CANDIDATE --reject-->      REJECTED      (an operator; a confirmed-normal
                                             calibration point, plan 4.4)
    CANDIDATE --expire-->      EXPIRED       (no operator acted in time)
    CONFIRMED --refresh-->     CONFIRMED     (a new fused score, incident ongoing)
    CONFIRMED --clear-->       CLEARED       (situation resolved)

REJECTED / EXPIRED / CLEARED are terminal. Every transition -- including the
rejections -- is appended to a hash-linked log on the `Incident` itself, so the
history is tamper-evident: this is the "refusals recorded, not just commands"
audit property the platform commits to. `verify_chain()` recomputes the whole
chain from the genesis hash.

This module owns only the *rules* (which transitions are legal, what the chain
hash is). Turning a transition into an `IncidentCandidate` / `IncidentDetected`
/ `IncidentUpdated` event on the bus is the producer's job in
sim-service/anomaly -- the domain layer has no dependency on `contracts/`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

# 64 hex zeros -- the prev_hash of the genesis entry, so "is this the start of a
# real chain" is a value check, not a None check.
GENESIS_HASH = "0" * 64


class IncidentState(StrEnum):
    """Matches contracts/events/incident_updated.avsc's IncidentState enum
    symbols exactly (upper-cased there, lower here for Python idiom -- the
    producer maps `.name`)."""

    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CLEARED = "cleared"


class IncidentAction(StrEnum):
    """What can be done to an incident. `RAISE` is the genesis action only --
    it is never a transition between two states, it creates the CANDIDATE."""

    RAISE = "raise"
    CONFIRM = "confirm"
    REJECT = "reject"
    EXPIRE = "expire"
    REFRESH = "refresh"
    CLEAR = "clear"


class IncidentClass(StrEnum):
    """Ground-truth / operator classification. STALL and LANE_BLOCK are the two
    the M6 injector produces; the rest are for real footage (M8). Mirrors
    incident_detected.avsc's IncidentClassification symbols."""

    STALL = "stall"
    LANE_BLOCK = "lane_block"
    DEBRIS = "debris"
    WRONG_WAY = "wrong_way"
    QUEUE_SPILLBACK = "queue_spillback"
    UNKNOWN = "unknown"


TERMINAL_STATES: frozenset[IncidentState] = frozenset(
    {IncidentState.REJECTED, IncidentState.EXPIRED, IncidentState.CLEARED}
)

# The full legal transition table. `RAISE` is deliberately absent -- it is not a
# state-to-state move, `raise_candidate` is its only path in.
_ALLOWED: Mapping[IncidentState, Mapping[IncidentAction, IncidentState]] = {
    IncidentState.CANDIDATE: {
        IncidentAction.CONFIRM: IncidentState.CONFIRMED,
        IncidentAction.REJECT: IncidentState.REJECTED,
        IncidentAction.EXPIRE: IncidentState.EXPIRED,
    },
    IncidentState.CONFIRMED: {
        IncidentAction.REFRESH: IncidentState.CONFIRMED,
        IncidentAction.CLEAR: IncidentState.CLEARED,
    },
}


class IllegalTransition(Exception):
    """Raised by `Incident.apply` for an action the current state does not
    permit -- a programming error in the caller, not a runtime condition to
    handle, so it is an exception rather than a returned `Violation` (unlike
    the interlocks, whose rejections are an expected control-flow outcome)."""


def _canonical(obj: object) -> bytes:
    """Deterministic bytes for hashing: sorted keys, no insignificant
    whitespace, `NaN`/`Infinity` rejected (json default)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_entry(
    *,
    action: IncidentAction,
    from_state: IncidentState | None,
    to_state: IncidentState,
    at_ms: int,
    actor: str,
    detail: str,
    graph_score: float | None,
    vision_score: float | None,
    fused_probability: float | None,
    threshold_tau: float | None,
    classification: IncidentClass | None,
    prev_hash: str,
) -> str:
    """SHA-256 over every field of a transition plus the previous entry's hash.
    Any edit to any recorded field, or any reordering of the log, changes this
    and every hash after it -- which is what `verify_chain` detects."""
    return hashlib.sha256(
        _canonical(
            {
                "action": action.value,
                "from_state": from_state.value if from_state is not None else None,
                "to_state": to_state.value,
                "at_ms": at_ms,
                "actor": actor,
                "detail": detail,
                "graph_score": graph_score,
                "vision_score": vision_score,
                "fused_probability": fused_probability,
                "threshold_tau": threshold_tau,
                "classification": classification.value if classification is not None else None,
                "prev_hash": prev_hash,
            }
        )
    ).hexdigest()


@dataclass(frozen=True)
class IncidentTransition:
    """One entry in the audit chain. Frozen -- a recorded transition is never
    edited in place; a correction is a new transition.

    `from_state` is `None` only on the genesis (`RAISE`) entry. The score
    fields carry the values *as of this transition* (a REFRESH records the new
    fused score; a CONFIRM records what the operator was looking at), so the
    chain is a complete history of what was known when, not just a list of
    state names."""

    action: IncidentAction
    from_state: IncidentState | None
    to_state: IncidentState
    at_ms: int
    actor: str
    detail: str = ""
    graph_score: float | None = None
    vision_score: float | None = None
    fused_probability: float | None = None
    threshold_tau: float | None = None
    classification: IncidentClass | None = None
    prev_hash: str = GENESIS_HASH
    entry_hash: str = ""

    def recomputed_hash(self) -> str:
        return _hash_entry(
            action=self.action,
            from_state=self.from_state,
            to_state=self.to_state,
            at_ms=self.at_ms,
            actor=self.actor,
            detail=self.detail,
            graph_score=self.graph_score,
            vision_score=self.vision_score,
            fused_probability=self.fused_probability,
            threshold_tau=self.threshold_tau,
            classification=self.classification,
            prev_hash=self.prev_hash,
        )


@dataclass(frozen=True)
class Incident:
    """One incident, from candidate to a terminal state. Immutable: every
    transition returns a new `Incident` (like the rest of the domain layer),
    so a caller that keeps a reference to an earlier value still has a
    consistent snapshot.

    `link_id` / `intersection_id` locate it on the network exactly as the
    detector's graph node does (`L{index}` + tls_id). The live score fields
    are the most recent values seen; `history` is the full hash-linked log,
    and `history[-1].entry_hash` is the chain head that goes on every emitted
    event so a store can prove it holds the same sequence.
    """

    incident_id: str
    link_id: str
    intersection_id: str
    first_seen_ms: int
    state: IncidentState
    classification: IncidentClass
    graph_score: float
    fused_probability: float
    threshold_tau: float
    vision_score: float | None = None
    false_alarm_budget: float = 0.05
    detector_version: str = ""
    history: tuple[IncidentTransition, ...] = field(default_factory=tuple)

    @property
    def chain_head(self) -> str:
        """The hash that goes on the next emitted event. `GENESIS_HASH` only
        for an `Incident` built by hand with no history -- `raise_candidate`
        always leaves at least the genesis entry."""
        return self.history[-1].entry_hash if self.history else GENESIS_HASH

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def confirmation_latency_ms(self) -> int | None:
        """`confirmed_at - first_seen` in ms, or None if never confirmed.
        The verification lag ADR-006 deliberately accepts as a cost."""
        for t in self.history:
            if t.action is IncidentAction.CONFIRM:
                return t.at_ms - self.first_seen_ms
        return None

    @classmethod
    def raise_candidate(
        cls,
        *,
        incident_id: str,
        link_id: str,
        intersection_id: str,
        at_ms: int,
        graph_score: float,
        fused_probability: float,
        threshold_tau: float,
        vision_score: float | None = None,
        false_alarm_budget: float = 0.05,
        detector_version: str = "",
        detail: str = "",
    ) -> Incident:
        """Create a CANDIDATE with its genesis audit entry. The only way an
        `Incident` legitimately comes into being."""
        genesis = _finalize(
            IncidentTransition(
                action=IncidentAction.RAISE,
                from_state=None,
                to_state=IncidentState.CANDIDATE,
                at_ms=at_ms,
                actor="detector",
                detail=detail,
                graph_score=graph_score,
                vision_score=vision_score,
                fused_probability=fused_probability,
                threshold_tau=threshold_tau,
                classification=None,
                prev_hash=GENESIS_HASH,
            )
        )
        return cls(
            incident_id=incident_id,
            link_id=link_id,
            intersection_id=intersection_id,
            first_seen_ms=at_ms,
            state=IncidentState.CANDIDATE,
            classification=IncidentClass.UNKNOWN,
            graph_score=graph_score,
            fused_probability=fused_probability,
            threshold_tau=threshold_tau,
            vision_score=vision_score,
            false_alarm_budget=false_alarm_budget,
            detector_version=detector_version,
            history=(genesis,),
        )

    def apply(
        self,
        action: IncidentAction,
        *,
        at_ms: int,
        actor: str,
        detail: str = "",
        classification: IncidentClass | None = None,
        graph_score: float | None = None,
        vision_score: float | None = None,
        fused_probability: float | None = None,
        threshold_tau: float | None = None,
    ) -> Incident:
        """Apply `action`, returning the resulting new `Incident`. Raises
        `IllegalTransition` if the current state does not permit `action`
        (including any action on a terminal state, and `RAISE`, which is never
        a transition).

        Score arguments left `None` carry forward the incident's current
        values into the log entry; passing them (typically on `REFRESH` or
        `CONFIRM`) records the updated numbers and moves the live fields.
        `classification` is normally set on `CONFIRM` -- the operator's call.
        """
        allowed = _ALLOWED.get(self.state, {})
        if action not in allowed:
            raise IllegalTransition(
                f"incident {self.incident_id} in {self.state.value} cannot {action.value} "
                f"(legal: {sorted(a.value for a in allowed)})"
            )
        to_state = allowed[action]

        new_graph = self.graph_score if graph_score is None else graph_score
        new_vision = self.vision_score if vision_score is None else vision_score
        new_fused = self.fused_probability if fused_probability is None else fused_probability
        new_tau = self.threshold_tau if threshold_tau is None else threshold_tau
        new_class = self.classification if classification is None else classification

        entry = _finalize(
            IncidentTransition(
                action=action,
                from_state=self.state,
                to_state=to_state,
                at_ms=at_ms,
                actor=actor,
                detail=detail,
                graph_score=new_graph,
                vision_score=new_vision,
                fused_probability=new_fused,
                threshold_tau=new_tau,
                classification=new_class if action is IncidentAction.CONFIRM else None,
                prev_hash=self.chain_head,
            )
        )
        return replace(
            self,
            state=to_state,
            classification=new_class,
            graph_score=new_graph,
            vision_score=new_vision,
            fused_probability=new_fused,
            threshold_tau=new_tau,
            history=self.history + (entry,),
        )

    def verify_chain(self) -> bool:
        """Recompute every entry's hash from its recorded fields and its
        predecessor, and confirm the links hold. Returns False on any edited
        field, reordered entry, or broken prev_hash link -- the tamper check.
        An `Incident` with no history verifies vacuously (True)."""
        prev = GENESIS_HASH
        for t in self.history:
            if t.prev_hash != prev:
                return False
            if t.entry_hash != t.recomputed_hash():
                return False
            prev = t.entry_hash
        return True


def _finalize(t: IncidentTransition) -> IncidentTransition:
    """Fill in `entry_hash` from the rest of the (already-set) fields."""
    return replace(t, entry_hash=t.recomputed_hash())
