# Event contracts

`[ARCH ADR-001]`: every data source, real or simulated, normalizes into the same
event language. This directory is that language — Avro schemas (`.avsc`), one file
per event type. All services import from here; nothing hand-rolls its own event
shape. Changing a schema without a compatible change is a CI-breaking offense
(build guide §6, "the discipline that makes this work") — that check gets wired up
once there's more than one event type to break compatibility with.

## Schemas

| File | Event | Added |
|---|---|---|
| `envelope.avsc` | Common envelope every event is wrapped in | M0 |
| `system_heartbeat.avsc` | Liveness/plumbing check — proves the bus works end to end | M0 |
| `vehicle_position_updated.avsc` | Per-vehicle position from the SUMO adapter | M1 |
| `approach_state.avsc` | Per-edge traffic state — **M1-simplified**, see the schema's own `doc` field for exactly what's a placeholder and what breaks when M4/M8 land | M1 |
| `signal_changed.avsc` | Emitted whenever the arbiter successfully commands a phase | M2 |
| `signal_faulted.avsc` | Emitted whenever the arbiter takes a failsafe/degraded branch (C1-C5) instead | M2 |
| `incident_candidate.avsc` | Anomaly stream raises this the first tick a link's fused score crosses the conformal threshold — not an incident until an operator confirms it | M6 |
| `incident_detected.avsc` | An operator confirmed a candidate into a real incident (ADR-006 human gate) — carries the confirming identity | M6 |
| `incident_updated.avsc` | Any later transition — reject / auto-expire / score refresh / clear. A rejection is the feedback signal the conformal calibrator consumes | M6 |
| `anomaly_create_requested.avsc` | Operator asks (via `commands.operator`) for an anomaly to be placed on a SUMO edge — the interactive counterpart to the automated injector | M6+ |
| `anomaly_clear_requested.avsc` | Operator clears / cancels an anomaly they created | M6+ |
| `anomaly_updated.avsc` | Live state of one anomaly on the network (ACTIVE / RESOLVED / CANCELLED), published on `anomaly.updated`. The normalised `itms_domain.anomaly.Anomaly` on the wire — operator and (later) graph/vision sources emit this same shape, distinguished by `source` | M6+ |
| `emergency_request_created.avsc` | Operator dispatches an emergency vehicle from a source to a destination (via `commands.operator`) — the router picks an anomaly-aware route | M7 |
| `emergency_command.avsc` | Follow-up operator action on a live request — RECALCULATE / CANCEL / ACTIVATE_CORRIDOR | M7 |
| `emergency_request_updated.avsc` | Live state of one `EmergencyRequest` (7-state lifecycle) on `emergency.request-updated`, carrying the chosen route + alternatives with their full cost breakdown | M7 |
| `emergency_vehicle_updated.avsc` | Position + status of one emergency vehicle while it drives through SUMO, on `emergency.vehicle-updated` | M7 |
| `green_corridor_updated.avsc` | Green corridor lifecycle on `emergency.corridor-updated` — the time-boxed movement reservations the Signal Controller turns into `corridor_preemption` proposals (it never commands a signal itself) | M7 |

Both M2 schemas are defined and their payload shape is real (matches `signal_controller/arbiter.py`'s `Decision.events` exactly) but **not yet published onto the bus** — M2 built and property-tested the safety kernel and arbitration ladder in isolation, against a fake cabinet; wiring a real producer into the running simulation is scoped to M3 (see `arbiter.py`'s module docstring for why).

The three M6 incident schemas are defined and roundtrip-tested (`packages/common/tests/test_incident_events.py`). The payload builders (`candidate_payload`/`detected_payload`/`updated_payload`) live in `itms_common/incident_events.py` — shared, not owned by either producer — because two independent services now publish these events: `sim_service/control/anomaly/live.py`'s `LiveIncidentDetector` publishes `IncidentCandidate` from the live simulation loop (via `sim_service/control/anomaly/events.py`'s `IncidentPublisher`, a thin sync-bus wrapper that re-exports the shared payload builders), and `api-service`'s `POST /v1/incidents/{id}/confirm|reject` endpoints publish `IncidentDetected`/`IncidentUpdated` (ADR-006's human gate — only an operator, through those endpoints, may confirm or reject a candidate). `api-service` also now consumes and broadcasts all three topics, and keeps an in-memory registry built by replaying them (`api_service/incidents.py`) — see PROGRESS.md's "Closing the integration gap" section for what was verified end to end against a real Redis instance.

The M6 gate script (`scripts/m6_incident_injection_gate.py`) still scores detections in-process via `scripts/m6_harness.py`'s `_Scorer` and never constructs a `LiveIncidentDetector` or publishes anything — that's deliberate, it's an offline accuracy measurement, not a live run. So: schema ✅, producer code ✅ and unit-tested, wired into a live run ✅ (though with no trained model shipped in this checkout, live detection is real code with nothing to detect yet — see README's "Current milestone"). The incident lifecycle these events describe is the state machine in `packages/domain/itms_domain/incident.py`.

More arrive as the milestone that needs them lands:

- M1 (remaining): `sensor_reading.avsc` (not needed yet — no IoT/loop-detector adapter exists)
- M2 (remaining): `signal_plan_proposed.avsc`, `signal_override_*.avsc` — no real proposer (M4 CA-MP) or overrider (M6) exists yet, same reasoning as M1's deferred `sensor_reading.avsc`
- M6: `emergency_dispatched.avsc`, `unit_reserved.avsc`, `route_calculated.avsc`
- M7: `corridor_reservation_*.avsc`, `fleet_position_updated.avsc` — still true even though M7 itself is done: the corridor engine and dispatcher (`control/corridor/`, `control/dispatch/`) are pure in-process simulation logic with zero bus involvement. Nothing about M7's verified benchmark result depends on these schemas existing; they'd only matter for a real multi-service deployment.
- M8: YOLO / vision detections feeding the same `anomaly_updated.avsc` shape

(The M1 `approach_state.avsc` already covers the `traffic.updated` topic — no separate M5 schema was ever needed; an earlier version of this list said otherwise.)

Full topic list with keys and retention: architecture doc §6.2.

## Envelope convention

Every event on the bus is the envelope (`envelope.avsc`) with a `payload` field
holding the event-specific Avro-encoded bytes, keyed by `event_type` +
`schema_version`. See `packages/common/itms_common/events.py` for the
(de)serialization helpers — encode/decode there, not ad hoc in each service.
