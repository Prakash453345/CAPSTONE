"""A real `CabinetPort` [ARCH §2.2] backed by a live TraCI connection to one
SUMO traffic light -- the M3 integration `cabinet.py`'s module docstring
flagged as deliberately deferred out of M2. This is what lets the
arbitration ladder actually govern real (simulated) signals instead of
only ever running against `FakeCabinet` in tests.

Scope note: SUMO offers no native fault-injection surface at this layer --
there's no way to make a simulated cabinet "trip its conflict monitor" or
"lose comms" the way `FakeCabinet` can. `comms_ok`, `hardware_override`,
and `booting` all stay at their healthy defaults here; C1-C5 stay covered
by the M2 fault-injection suite against `FakeCabinet`, which is the right
split -- faults are a property of the *cabinet abstraction's contract*,
provable once, not something that needs re-proving per backend.

This module only implements the `CabinetPort` protocol itself (what the
arbiter needs: command one green phase, read state, command all-red). The
mechanical yellow/all-red sub-phase sequencing a transition needs -- SUMO
has no notion of "hold yellow for N seconds" as a single command -- is
runner-level bookkeeping, not a cabinet responsibility; see
`control/runner.py` and `yellow_state_for`/`all_red_state` below, which the
runner calls directly rather than through `CabinetPort`.
"""

from __future__ import annotations

from collections.abc import Mapping

import traci
from itms_domain import Phase

from sim_service.signal_controller.cabinet import CabinetReadback


class TraCICabinet:
    """One instance per signal-controlled junction. `phases` should be the
    same `Tier0Config.phases` the arbiter is checking plans against for
    this junction -- the state strings this class builds are exactly
    length `state_len`, 'G' at each phase's green link indices, 'r'
    elsewhere, matching the tlLogic state-string convention
    `extract_tier0_config.py` read them from in the first place.
    """

    def __init__(
        self,
        tls_id: str,
        phases: Mapping[str, Phase],
        state_len: int,
        *,
        preserve_permissive: bool = True,
    ):
        self._tls_id = tls_id
        self._phases = phases
        self._state_len = state_len
        self._preserve_permissive = preserve_permissive
        self._state_by_phase = {
            phase_id: self._build_state(phase) for phase_id, phase in phases.items()
        }
        self._all_red = "r" * state_len

    def _build_state(self, phase: Phase) -> str:
        """'G' for protected, 'g' for permissive, 'r' elsewhere.

        The distinction is load-bearing and this class did not make it
        until M7. SUMO's two green characters are not cosmetic: 'G' means
        "green with priority -- do not yield", 'g' means "green, yield to
        foes". `extract_tier0_config.py` reads that distinction out of the
        net into `Phase.protected_movements` precisely so `interlocks.
        no_conflicting_greens` can skip permissive movements, whose safety
        SUMO enforces dynamically instead (see `Phase`'s own docstring:
        "SUMO enforces a dynamic yield check for those at runtime").

        This class then wrote 'G' for every member of `green_movements`,
        which withdraws exactly the dynamic yield check the interlock was
        relying on. The two halves of the argument were each correct and
        their conjunction was not: I1 skipped the permissive movements
        because SUMO would handle them, and the cabinet told SUMO not to.

        It matters here and not only in principle. Nine link indices
        across four of this corridor's seven junctions are permissive in
        the net (`cluster_11608007559_1880441514` L8/L12/L13/L3,
        `cluster_1880441532_4393295467` the same, `cluster_1880441541_
        4393295474` L3, `cluster_1880441740_4393296791` L15/L6), and every
        one of them conflicts with a protected movement in its own phase
        -- L12 against L4/L5/L6/L7, L15 against L3/L4/L5, and so on. Under
        the old state string those pairs ran simultaneously with neither
        one yielding. Measured on the medium scenario, identical net,
        demand and seeds, `--collision.check-junctions true`:

            seed   SUMO's own program   this cabinet ('G')   with 'g'
            1      0                    3 (2 at junctions)   0
            2      0                    1                    0
            3      0                    1 (1 at junction)    1

        One collision survives the fix, at an internal lane of the
        `cluster_1880441532` cluster on seed 3; its cause is not
        established and it is recorded here rather than rounded down to
        zero.

        `preserve_permissive=False` restores the old string exactly, and
        exists for one reason: the M3/M4/M5 results recorded in
        PROGRESS.md were all measured under it, and a recorded experiment
        whose harness has silently changed underneath it is worse than a
        recorded experiment with a known caveat. Those numbers are
        reproducible by passing the flag; new work should not."""
        protected = phase.protected_movements or phase.green_movements
        prot_idx = {int(m.removeprefix("L")) for m in protected}
        all_idx = {int(m.removeprefix("L")) for m in phase.green_movements}
        perm_idx = set() if not self._preserve_permissive else all_idx - prot_idx
        return "".join(
            "G" if i in (all_idx - perm_idx) else "g" if i in perm_idx else "r"
            for i in range(self._state_len)
        )

    def _phase_id_for_state(self, state: str) -> str | None:
        for phase_id, phase_state in self._state_by_phase.items():
            if state == phase_state:
                return phase_id
        return None  # mid-transition (yellow/all-red) or an unrecognized state

    def read_state(self) -> CabinetReadback:
        current = traci.trafficlight.getRedYellowGreenState(self._tls_id)
        return CabinetReadback(phase_id=self._phase_id_for_state(current))

    def command(self, phase_id: str) -> bool:
        state = self._state_by_phase.get(phase_id)
        if state is None:
            return False
        traci.trafficlight.setRedYellowGreenState(self._tls_id, state)
        return True

    def command_all_red(self) -> None:
        traci.trafficlight.setRedYellowGreenState(self._tls_id, self._all_red)

    # -- runner-only helpers, not part of CabinetPort ----------------------

    def yellow_state_for(self, phase_id: str) -> str:
        """The departing phase's green links shown as yellow, everything
        else red -- what the physical signal head shows during the
        clearance interval `PlanStep.yellow_s` covers.

        Both green characters become yellow. A permissive movement is a
        movement being displayed a green ball; dropping it straight to red
        would omit its yellow change interval entirely, which MUTCD 11th
        Ed. §4F.18 forbids without qualification ("the yellow change
        interval, and any red clearance interval that follows, shall not
        be shortened or omitted") and which is a rear-end crash mechanism
        in its own right. This mattered only once `_build_state` started
        emitting 'g' at all; before that every green link was 'G' and the
        distinction could not arise."""
        green_state = self._state_by_phase[phase_id]
        return "".join("y" if c in "Gg" else "r" for c in green_state)

    def all_red_state(self) -> str:
        return self._all_red

    def carried_clearance_states(self, outgoing: str, incoming: str) -> tuple[str, str]:
        """`(yellow stage, red stage)` for a change between a ring phase and
        one of its alternates (`Tier0Config.alternates`: the same approach
        served alone), where some links are green on both sides of the
        change. Such a link is *carried through* the clearance instead of
        being stopped for it:

        - green before and after with the same character: it keeps it;
        - permissive before, protected after ('g' -> 'G'): it stays 'g',
          still yielding, until the clearance is over;
        - protected before, permissive after ('G' -> 'g'): **not** carried.
          Its protection is being withdrawn, so it gets its yellow and red
          like a departing link before the stream it must now yield to
          starts;
        - every other green link: yellow, then red, as in `yellow_state_for`.

        The links carried were already green together with the departing
        ones in the outgoing phase, so nothing is shown during the clearance
        that the outgoing phase did not show.

        The runner shows these only when `carry_is_trap_free` says so."""
        out_state = self._state_by_phase[outgoing]
        in_state = self._state_by_phase[incoming]
        yellow, red = [], []
        for a, b in zip(out_state, in_state, strict=True):
            keep = a in "Gg" and (b == a or (a == "g" and b == "G"))
            yellow.append(a if keep else "y" if a in "Gg" else "r")
            red.append(a if keep else "r")
        return "".join(yellow), "".join(red)

    def carry_is_trap_free(self, outgoing: str, incoming: str) -> bool:
        """Whether `carried_clearance_states(outgoing, incoming)` may be
        shown: no *permissive* link is stopped by it. A permissive movement
        is one whose driver waits in the junction for a gap in a stream that
        has a green. Stop that driver with a yellow while the stream keeps
        its green, and the yellow says "they are stopping too" when they are
        not -- the yellow trap. A link that is permissive on both sides, or
        gains protection, is not stopped; a protected link that is stopped
        yields to nobody, so its yellow tells it nothing false."""
        out_state = self._state_by_phase[outgoing]
        in_state = self._state_by_phase[incoming]
        return not any(a == "g" and b not in "Gg"
                       for a, b in zip(out_state, in_state, strict=True))

    def set_raw_state(self, state: str) -> None:
        """Direct escape hatch for the runner's yellow/all-red sequencing --
        deliberately outside `CabinetPort` (see module docstring)."""
        traci.trafficlight.setRedYellowGreenState(self._tls_id, state)
