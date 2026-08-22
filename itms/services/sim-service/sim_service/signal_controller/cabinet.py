"""The boundary between the arbiter and physical (or simulated) signal
hardware [ARCH §2.2, build guide C1-C5]. `CabinetPort` is the interface the
arbiter programs against; `FakeCabinet` is the deterministic, fault-
injectable implementation the M2 test suite drives.

A real TraCI-backed cabinet (commanding SUMO's traffic lights, reading back
`traci.trafficlight.getRedYellowGreenState()`) is real, necessary work --
and deliberately not built in this pass. M2's job is the safety kernel and
the arbitration ladder in isolation, proven against a fault-injectable
fake; wiring an implementation of this exact port into the live Vijayawada
corridor scenario is naturally M3's job (the baseline strategies are what
first need to actually move real (simulated) traffic lights). Building the
integration before the kernel it will run inside is proven safe would be
building the optimiser before the safety net -- the mistake build guide
§7's sequencing principle exists to prevent, one layer up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CabinetReadback:
    """What the cabinet reports right now, independent of what was last
    commanded -- the arbiter's only source of truth about physical state."""

    phase_id: str | None
    """What the cabinet says is live. None if genuinely unknown (comms down,
    or freshly booted with no state yet)."""

    hardware_override: bool = False
    """True only when the cabinet's OWN protection hardware (conflict
    monitor) forced flash mode without being asked -- C2. While true, the
    arbiter must observe, not command."""

    booting: bool = False
    """True only immediately after a power cycle, before any post-boot
    command has been issued -- C4's "unknown state at boot"."""

    comms_ok: bool = True
    """False means this read (or the arbiter's last command) didn't reach
    the cabinet at all -- C3. A `CabinetReadback` with `comms_ok=False`
    carries no trustworthy `phase_id`."""


class CabinetPort(Protocol):
    def read_state(self) -> CabinetReadback: ...

    def command(self, phase_id: str) -> bool:
        """Command one phase live. Returns whether it was acknowledged --
        False means treat the resulting state as unknown (C3), not assume
        the command landed."""
        ...

    def command_all_red(self) -> None:
        """A *controller-issued* failsafe (C4's forced startup sequence, or
        rung-1 fallback when no legal plan exists) -- distinct from
        `hardware_override`, which is the cabinet overriding *us*."""
        ...


class FakeCabinet:
    """In-memory, deterministic, fault-injectable `CabinetPort`. The
    `trip_*` / `drop_*` / `diverge_*` methods below are the fault-injection
    hooks the C1-C5 tests use; nothing in the arbiter calls them."""

    def __init__(self) -> None:
        self._reported_phase: str | None = None
        self._hardware_override = False
        self._booting = False
        self._comms_ok = True

    def read_state(self) -> CabinetReadback:
        if not self._comms_ok:
            return CabinetReadback(phase_id=None, comms_ok=False)
        return CabinetReadback(
            phase_id=self._reported_phase,
            hardware_override=self._hardware_override,
            booting=self._booting,
            comms_ok=True,
        )

    def command(self, phase_id: str) -> bool:
        if not self._comms_ok:
            return False
        if self._hardware_override:
            # The cabinet is fighting back -- refuse the command rather than
            # silently pretending it landed (C2: "never fight the hardware").
            return False
        self._reported_phase = phase_id
        self._booting = False  # a defined command is the resume C4 asks for
        return True

    def command_all_red(self) -> None:
        if not self._comms_ok:
            return
        self._reported_phase = None
        self._booting = False

    # -- fault injection, test-only ---------------------------------------

    def trip_conflict_monitor(self) -> None:
        """C2: the cabinet forces flash on its own."""
        self._hardware_override = True
        self._reported_phase = None

    def clear_conflict_monitor(self) -> None:
        self._hardware_override = False

    def drop_comms(self) -> None:
        """C3: comms to the cabinet are lost."""
        self._comms_ok = False

    def restore_comms(self) -> None:
        self._comms_ok = True

    def simulate_power_cycle(self) -> None:
        """C4: power failure and restart -- state is unknown until a
        defined resume (the next successful `command()`)."""
        self._reported_phase = None
        self._hardware_override = False
        self._booting = True
        self._comms_ok = True

    def force_diverge(self, reported_phase: str | None) -> None:
        """C5 / E1: make the cabinet report something the controller didn't
        command -- a manual field override or a genuine hardware fault both
        look like this from the controller's side."""
        self._reported_phase = reported_phase
