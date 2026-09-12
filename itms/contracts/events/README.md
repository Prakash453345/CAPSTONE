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
| `incident_candidate.avsc` | Anomaly-detected incident candidate — raised before operator confirmation | M6 |
| `incident_detected.avsc` | Operator/auto-confirmed incident — consumed by dispatch, routing, corridor | M6 |
| `incident_updated.avsc` | Incident lifecycle change: rejected, resolved, or escalated | M6 |

Both M2 schemas are defined and their payload shape is real (matches `signal_controller/arbiter.py`'s `Decision.events` exactly) but **not yet published onto the bus** — M2 built and property-tested the safety kernel and arbitration ladder in isolation, against a fake cabinet; wiring a real producer into the running simulation is scoped to M3 (see `arbiter.py`'s module docstring for why).

More arrive as the milestone that needs them lands:

- M1 (remaining): `sensor_reading.avsc` (not needed yet — no IoT/loop-detector adapter exists)
- M2 (remaining): `signal_plan_proposed.avsc`, `signal_override_*.avsc` — no real proposer (M4 CA-MP) or overrider (M6) exists yet, same reasoning as M1's deferred `sensor_reading.avsc`
- M5: `traffic_updated.avsc`
- M6 (delivered): `incident_candidate.avsc`, `incident_detected.avsc`, `incident_updated.avsc`
- M6: `emergency_dispatched.avsc`, `unit_reserved.avsc`, `route_calculated.avsc`
- M7: `corridor_reservation_*.avsc`, `fleet_position_updated.avsc`

Full topic list with keys and retention: architecture doc §6.2.

## Envelope convention

Every event on the bus is the envelope (`envelope.avsc`) with a `payload` field
holding the event-specific Avro-encoded bytes, keyed by `event_type` +
`schema_version`. See `packages/common/itms_common/events.py` for the
(de)serialization helpers — encode/decode there, not ad hoc in each service.
