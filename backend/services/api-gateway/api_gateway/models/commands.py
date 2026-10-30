from __future__ import annotations

from pydantic import BaseModel, Field


class CommandRequest(BaseModel):
    """An operator action to run against the live simulation. `event_type`
    selects the payload schema in `contracts/events/`; `payload` must match
    it. The command is wrapped in the standard EventEnvelope and published on
    `commands.operator`, which the simulation service (SIM_MODE=live) drains
    each tick.

    Deliberately thin: this service does no business logic here -- it is the
    adapter that gets an operator intent onto the bus. The simulation service
    owns applying it to SUMO, and the Signal Controller stays the only thing
    that can command a signal."""

    event_type: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    operator: str = Field(default="operator:console", min_length=1)
