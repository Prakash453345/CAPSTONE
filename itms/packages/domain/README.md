# packages/domain

Entities, value objects, and state machines — no I/O `[ARCH §6, repo layout]`.

**M2** (current): `itms_domain.signal` — the safety-kernel's predicate types.
`SignalPlan`, `PlanStep`, `JunctionContext`, `Tier0Config`, `Phase`, `Violation`.
Pure dataclasses, no bus/DB/clock imports — that's what lets
`services/sim-service/sim_service/control/safety/interlocks.py` run the exact
same code inside the live controller and inside a Hypothesis property test.
See that module and `signal.py`'s own docstrings for what's modeled generically
here vs. mapped onto real junction geometry (deferred; see `interlocks.py`'s
module docstring).

Grows again in **M6** with the incident state machine (schema-enforced
transitions, architecture §5.2).

**M8**: `itms_domain.camera` — camera state in a `JunctionContext`: the swap
of the four queue-state fields for a camera estimate, the confidence policy
(`failsafe` / `honest` / `trust`) and `BlindCameraCheck`, the stop-bar
cross-check that catches a camera still sending frames but no longer finding
vehicles. Pure, like the rest of this package, so the live adapter
(`sim_service.control.vision_feed`) and the gates' adapter
(`vision_service.sim.closed_loop`) run the same code.
