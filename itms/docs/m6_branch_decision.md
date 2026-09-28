# M6: why the `VIVEK` branch is not merged

**Decision (2026-09-23): keep this branch's M6 anomaly-detection stack. Do not
merge `origin/VIVEK`.**

`VIVEK` branched at `ddc7b0d`, before M6 landed here in `87ff903`. Both branches
then built a complete anomaly-detection and incident-lifecycle stack, without
knowledge of each other. They are not two halves of one feature; they are two
implementations of the same milestone, and they disagree on the wire contract.

## The contracts are incompatible

`incident_candidate` / `incident_detected` / `incident_updated` exist on both
branches with different fields:

| | this branch | `VIVEK` |
| --- | --- | --- |
| identity | `incident_id`, stable across the lifecycle | `candidate_id`, plus a separate `incident_id` at confirmation |
| fused score | `fused_probability` — `double`, `[0,1]` | `fused_score` — `float` |
| threshold | `threshold_tau` | `threshold` |
| lifecycle state | `IncidentState` enum | free-text `new_status` |
| classification | `IncidentClassification` enum | free-text `severity` |
| audit | `chain_hash`, hash-linked per transition | *none* |
| latency basis | `sim_tick` | *none* |
| provenance | `detector_version`, `false_alarm_budget` | *none* |

## Consumers here already depend on those fields

Adopting `VIVEK`'s schema would break, not extend:

- `services/api-service/api_service/incidents.py` — the incident registry keys
  its idempotency check on `chain_hash` and parses `new_state` as `IncidentState`.
- `web-app/src/services/traffic/incidents.ts` and `wsProvider.ts` — read
  `fused_probability`.
- `packages/domain/itms_domain/incident.py` — the audit chain the `chain_hash`
  values come from.

## And the implementation here is the larger one

`services/sim-service/sim_service/control/anomaly/` is ~2,300 lines across
`detector`, `fusion`, `graph_features`, `calibration`, `injector` and `live`,
wired into the control path, with the domain audit chain alongside it.
`VIVEK`'s `packages/anomaly/` detector is ~150 lines and has no equivalent of
`graph_features`, `injector` or `live`; its `services/incident-service/` is a
separate microservice for work this branch does in-process.

`VIVEK` also carries `web/incidents.js` and `web/live.html`, which target the
vanilla-JS UI that `web-app/` replaced.

## What was worth taking

`infra/postgres/init/003_incidents.sql` is the one thing `VIVEK` has that this
branch lacks — the incident registry here is in-memory. It was **not** ported:
the schema is written against `VIVEK`'s field names throughout. If incident
persistence is wanted, write it against `itms_domain.incident` instead.

The branch remains on GitHub; nothing was deleted.
