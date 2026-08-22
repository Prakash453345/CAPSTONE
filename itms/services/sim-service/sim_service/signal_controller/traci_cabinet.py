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

    def __init__(self, tls_id: str, phases: Mapping[str, Phase], state_len: int):
        self._tls_id = tls_id
        self._phases = phases
        self._state_len = state_len
        self._state_by_phase = {
            phase_id: self._build_state(phase.green_movements) for phase_id, phase in phases.items()
        }
        self._all_red = "r" * state_len

    def _build_state(self, green_movements: frozenset[str]) -> str:
        green_indices = {int(m.removeprefix("L")) for m in green_movements}
        return "".join("G" if i in green_indices else "r" for i in range(self._state_len))

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
        clearance interval `PlanStep.yellow_s` covers."""
        green_state = self._state_by_phase[phase_id]
        return "".join("y" if c == "G" else "r" for c in green_state)

    def all_red_state(self) -> str:
        return self._all_red

    def set_raw_state(self, state: str) -> None:
        """Direct escape hatch for the runner's yellow/all-red sequencing --
        deliberately outside `CabinetPort` (see module docstring)."""
        traci.trafficlight.setRedYellowGreenState(self._tls_id, state)
