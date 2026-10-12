"""Dispatch: where an emergency vehicle should go, and by which route.

The layer above the Green Corridor Engine. `facilities.py` holds the
destinations and is explicit about which of its data is observed and
which is modelled; `dispatcher.py` chooses among them by live travel
time. Neither can command a signal.
"""

from sim_service.control.dispatch.dispatcher import (
    DispatchDecision,
    IncidentRequest,
    RouteFn,
    capability_coverage,
    choose,
    should_redispatch,
    summarise,
)
from sim_service.control.dispatch.facilities import GENERAL, Facility, FacilityIndex

__all__ = [
    "GENERAL",
    "DispatchDecision",
    "Facility",
    "FacilityIndex",
    "IncidentRequest",
    "RouteFn",
    "capability_coverage",
    "choose",
    "should_redispatch",
    "summarise",
]
