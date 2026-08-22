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
