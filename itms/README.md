# ITMS — Intelligent Traffic Management & Emergency Response Platform

Capstone implementation, built milestone by milestone against `ITMS Build Guide` v1.0
(companion to `smart-traffic-platform-architecture.md` v1.1 and
`platform-architecture-diagram.mermaid`). Those three documents are the spec; this
repo is the build. Where this README and the docs disagree, the docs win — fix the
README.

## Current milestone

**M5, M6, and M7 are all built. What's real and what isn't, briefly:**

- **M5 — A-CA-MP (adaptive signal control) — done.** Beats tuned Webster at
  light demand, ties at medium, and (after the `protect_allocated_green`
  fix) beats it by 12.1% at heavy demand too -- the one open item noted in
  earlier snapshots of this README is closed.
- **M6 — anomaly detection (incident spotting) — built end to end, not yet
  accurate.** The full pipeline (graph-based detector, conformal alert
  threshold, incident state machine, event schemas) is implemented and
  unit-tested (~105 dedicated tests). The trained model itself has only
  seen a tiny proof-of-training run (2 scenarios, 12 epochs) and does not
  yet meet its own accuracy gate (recall 0.50 vs a 0.90 target on 1 eval
  seed) -- see `ITMS_M6_Anomaly_Detection_Status_and_Accuracy_Plan.docx`
  for the honest current numbers and the prioritized plan to close the gap
  (mainly: record the full 30-scenario dataset and train longer).
- **M7 — green corridor (emergency vehicle preemption) + dispatch — done,
  verified.** Real, measured wins against field-standard reactive
  preemption at medium demand: EV travel time -3.5% to -4.3%, time loss
  -25% to -31%, stops -31% to -46%, all statistically significant, with no
  measurable cost to cross-street traffic. One negative result reported
  honestly: the "anticipation" and "debt-recovery" pressure terms
  (Contribution 1) do not show a measurable benefit on 30 paired seeds at
  either medium or heavy demand, and remain on by default but unproven.
  Dispatch adds real hospital-destination routing pulled from map data.
- **Integration gap: partly closed.** `make dev`'s live demo used to run
  `traci_loop.run` -- SUMO's own default signal program, none of M2-M7's
  control logic, ever, on any live run. It now runs
  `control/runner.run_controlled_scenario` with A-CA-MP actually governing
  every junction (cold-started, no warmed memory profile) and M6's
  `LiveIncidentDetector` wired in (a documented no-op today, since no
  trained model ships in this checkout -- see M6's bullet above).
  `api-service` now consumes `incident.candidate`/`.detected`/`.updated`,
  broadcasts them over the same WebSocket, keeps an in-memory incident
  registry, and exposes `POST /v1/incidents/{id}/confirm|reject`
  (ADR-006's human gate, protected by a simple shared-secret header) plus
  read-only `GET /v1/incidents[/{id}]`. Verified end to end against a real
  Redis instance and, separately, a real SUMO run -- see PROGRESS.md's
  "Closing the integration gap" section for exactly what was checked.
  **Still not wired into the live demo:** M7's corridor engine / EV
  preemption (dispatch and green-corridor logic still only run inside
  benchmark scripts), and a trained M6 model (the shipped detector is still
  proof-of-training only, so live incident detection is real code with
  nothing to detect yet).

- **Interactive layer, on top of the above:** operator-driven anomaly
  injection that affects the SUMO simulation, a dynamic anomaly-aware
  emergency router, and continuous re-routing of a moving vehicle --
  `SIM_MODE=live` (`sim_service.live.service.run_live`), independent of the
  benchmarked M7 corridor engine above (both propose through the same
  arbiter + interlocks; see `arbiter.tick`'s docstring for why there are
  two rung-3 requesters). Full description, cost formula, config
  reference, event contracts, lifecycles, and a run/demo guide:
  **[`docs/interactive-emergency-response.md`](docs/interactive-emergency-response.md)**.

See `PROGRESS.md` for the full history, every number, and every negative
result, with dates.

## Quick start

Requires Docker + Docker Compose, Python 3.11+, and `make`.

```bash
make dev         # starts postgres+postgis+timescale, redis, minio; runs sim-service
                 # and api-service; prints the URL for the demo page
make test        # full suite except the M6 anomaly-detector tests (they need the
                 # optional [anomaly] extra -- see test-anomaly below); includes
                 # the ~55s, 10,000-example-per-invariant safety property suite
make test-fast   # same as test, minus that slow property suite -- quick dev loop
make test-anomaly # installs numpy/torch and runs just the M6 detector tests
make test-all    # everything, including the anomaly extra -- what CI should run
make lint        # ruff + mypy
make down        # stop the stack
```

Then open `web/index.html` in a browser (or `make dev` will print the exact URL) —
it connects to the api-service WebSocket, shows a live map of the Vijayawada
corridor with A-CA-MP actually controlling every signal (not SUMO's default
program), and keeps a raw event log alongside for debugging. Any raised
incident candidates show up on the same stream; confirming or rejecting one
needs `curl -X POST -H "X-API-Key: <key>" .../v1/incidents/{id}/confirm` --
set `API_KEY` yourself, or read the one api-service generates and logs on
startup when it isn't set (fine for local dev, not for anything else).

To load the road network into PostGIS (separate from the SUMO scenario files,
which sim-service reads directly):

```bash
.venv/bin/python infra/postgres/import_road_network.py \
  --geojson scenarios/networks/vijayawada/vijayawada_corridor.geojson \
  --network-name vijayawada_corridor
```

## Why it's built this way

The core architectural bet, from the architecture doc: **every data source is an
adapter behind a common event contract.** `contracts/events/` is that contract. All
services import from it; nothing hand-rolls its own event shape. This is cheap now
and expensive to retrofit later, so it exists from milestone zero — `SystemHeartbeat`
(M0), then `VehiclePositionUpdated` / `ApproachState` (M1), growing one milestone
at a time rather than all ~15 event types being stubbed out now with nothing to
validate them against.

Phase-1 collapses the 20-service catalog from the architecture doc into three
deployables — `sim-service`, `api-service`, `vision-service` — with Redis Streams
standing in for Kafka. Internal module boundaries mirror the full service catalog
so later extraction into real microservices is mechanical, not archaeological. See
`services/*/README.md` (added as each service grows) for which architecture
services live where.

## Repo layout

```
itms/
├── docker-compose.yml       # postgres+postgis+timescale, redis, minio
├── Makefile                 # make dev / make test (+ test-fast/-anomaly/-all) / make lint / make down
├── contracts/                # ONE event language — shared by all services
│   └── events/*.avsc
├── packages/
│   ├── common/               # event bus client (Redis Streams now, Kafka later, ADR-003)
│   ├── domain/                # entities, value objects, state machines — safety-kernel types as of M2;
│   │                          # +incident.py, the M6 incident lifecycle + hash-chained audit
│   └── geo/                   # homography, ground-plane projection — arrives M8
├── services/
│   ├── sim-service/          # [ARCH] services 3,4,5,17,19,20 — traffic state, control, adapters
│   │   └── sim_service/
│   │       ├── adapters/sumo/       # TraCI loop (M1)
│   │       ├── control/safety/      # L0 interlocks — pure predicates (M2)
│   │       ├── control/strategies/  # fixed_time (M2); webster/actuated (M3); camp (M4); acamp (M5)
│   │       ├── control/memory.py, tuning.py, online_calibration.py  # M5's learning layer
│   │       ├── control/anomaly/     # M6: graph autoencoder, conformal calibration, fusion,
│   │       │                        # incident injector — built + tested, undertrained (see README top)
│   │       ├── control/corridor/    # M7: green corridor engine (engine/junction/requests/debt) —
│   │       │                        # built, verified, rung 3 of the arbitration ladder
│   │       ├── control/dispatch/    # M7: hospital-destination routing from real facility data
│   │       └── signal_controller/   # arbitration ladder + cabinet port (M2); +lane_cache,
│   │                                # discharge_observer (M5); +ev_detection.py, ev_routing.py (M7)
│   ├── api-service/          # [ARCH] services 6,8-12,14,15 — incidents, dispatch, routing, corridor,
│   │                          # config, audit are the ARCHITECTURE's intended scope for this service.
│   │                          # Implemented: M1 streaming (heartbeat/vehicle-position/traffic-state)
│   │                          # + M6 incidents (consume incident.* topics, confirm/reject endpoints,
│   │                          # simple API-key auth). Dispatch/routing/corridor not yet built —
│   │                          # see "Current milestone" above.
│   └── vision-service/       # [ARCH] services 7,18 — vision pipeline, camera ingestion
├── scenarios/                 # networks + demand for real/synthetic areas; suite/ (acceptance tests) arrives M2+
│   └── networks/vijayawada/facilities.json  # M7: 103 real hospitals/clinics, extracted from OSM
├── infra/postgres/           # PostGIS schema + road-network import script
├── cases/atlas.yaml          # the case atlas, machine-readable — arrives M2+
├── bench/                     # benchmark harness — arrives M3
├── notebooks/                 # calibration notebooks — arrives M8
├── docs/                      # design write-ups too long for PROGRESS.md: the M7 hazard catalogue
│                                # (86 cataloged failure modes), the corridor algorithm design,
│                                # the dispatch/destinations design, an incident-pipeline analysis
├── scripts/                   # gate/benchmark/diagnostic scripts (M3-M7), one per experiment
│   └── results/                # every script's generated JSON output — never hand-edited,
│                                # regenerate by re-running the script that wrote it
└── web/                       # demo page — live map as of M1, grows with each milestone
```

## Milestone map

| # | Milestone | Status |
|---|---|---|
| M0 | Skeleton | ✅ done |
| M1 | SUMO adapter and traffic state | ✅ done |
| M2 | Safety kernel (L0 interlocks) | ✅ done |
| M3 | Baselines and KPI harness (Webster) | ✅ done |
| M4 | CA-MP Layer 1 | ✅ done — loses to Webster; superseded by M5 |
| M5 | A-CA-MP (adaptive, with memory) | ✅ done — beats Webster at all three demand levels |
| M6 | Anomaly detection (incident spotting) | ⚠️ built + tested, model undertrained — not gate-passing yet |
| M7 | Green corridor + dispatch | ✅ done, verified — Contribution 1 pressure terms unproven (honest negative result) |
| — | `api-service` catching up to M6/M7 | ⚠️ M1 + M6 incidents done; M7 corridor/dispatch endpoints not built, see README top |
| M8 | Vision on real footage | not started |
| M9 | Benchmark, evaluation, site | not started |

Full detail for each milestone (demo + gate) is in the build guide §7.
