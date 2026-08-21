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

More arrive as the milestone that needs them lands:

- M1: `vehicle_position_updated.avsc`, `approach_state.avsc`, `sensor_reading.avsc`
- M2: `signal_plan_proposed.avsc`, `signal_changed.avsc`, `signal_override_*.avsc`, `signal_faulted.avsc`
- M5: `traffic_updated.avsc`
- M6: `incident_candidate.avsc`, `incident_detected.avsc`, `incident_updated.avsc`
- M6: `emergency_dispatched.avsc`, `unit_reserved.avsc`, `route_calculated.avsc`
- M7: `corridor_reservation_*.avsc`, `fleet_position_updated.avsc`

Full topic list with keys and retention: architecture doc §6.2.

## Envelope convention

Every event on the bus is the envelope (`envelope.avsc`) with a `payload` field
holding the event-specific Avro-encoded bytes, keyed by `event_type` +
`schema_version`. See `packages/common/itms_common/events.py` for the
(de)serialization helpers — encode/decode there, not ad hoc in each service.
