"""Green Corridor Engine -- rung 3 of the arbitration ladder [ARCH §2.2].

Emergency-vehicle preemption coordinated across a route rather than
decided independently at each junction. See `engine.py` for what that buys
and what it costs, `junction.py` for the per-junction state machine and
the rule that a rejected preemption is a denial rather than a fault, and
`debt.py` for what preemption owes the movements it stops.
"""

from sim_service.control.corridor.debt import DebtLedger
from sim_service.control.corridor.engine import CorridorConfig, CorridorEngine
from sim_service.control.corridor.junction import (
    Confirmation,
    DeferReason,
    JunctionPreemption,
    PreemptState,
    ReleaseReason,
    protected_phase_for,
    transfer_time,
)
from sim_service.control.corridor.requests import (
    PreemptionClass,
    Reservation,
    VehicleReport,
)

__all__ = [
    "Confirmation",
    "CorridorConfig",
    "CorridorEngine",
    "DebtLedger",
    "DeferReason",
    "JunctionPreemption",
    "PreemptState",
    "PreemptionClass",
    "ReleaseReason",
    "Reservation",
    "VehicleReport",
    "protected_phase_for",
    "transfer_time",
]
