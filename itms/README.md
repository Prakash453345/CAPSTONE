# ITMS — Intelligent Traffic Management & Emergency Response Platform

Capstone implementation, built milestone by milestone against `ITMS Build Guide` v1.0
(companion to `smart-traffic-platform-architecture.md` v1.1 and
`platform-architecture-diagram.mermaid`). Those three documents are the spec; this
repo is the build. Where this README and the docs disagree, the docs win — fix the
README.

## Current milestone

**M1–M6 done. Interactive emergency-response layer (routing, green corridor,
continuous re-routing) built on top.**

- M2–M5: safety kernel + arbitration ladder + adaptive signal control (A-CA-MP);
  beats tuned Webster at light demand, ties at medium, ~7% loss at heavy (still
  open — see `PROGRESS.md`).
- M6: graph-autoencoder anomaly detection with conformal alerting.
- **Interactive layer:** operator-driven anomaly injection that affects the SUMO
  simulation, a dynamic anomaly-aware emergency router, a green corridor that
  proposes signal preemptions through the existing arbiter + interlocks (never
  commanding a signal directly), and continuous re-routing of a moving vehicle.
  Full description, cost formula, config reference, event contracts, lifecycles,
  and a run/demo guide: **[`docs/interactive-emergency-response.md`](docs/interactive-emergency-response.md)**.

See `PROGRESS.md` for the milestone-by-milestone history.

## Quick start

Requires Docker + Docker Compose, Python 3.11+, and `make`.

```bash
make dev     # starts postgres+postgis+timescale, redis, minio; runs sim-service
             # and api-service; prints the URL for the demo page
make test    # runs the test suite across packages/ and services/
make lint    # ruff + mypy
make down    # stop the stack
```

Then open `web/index.html` in a browser (or `make dev` will print the exact URL) —
it connects to the api-service WebSocket, shows a live map of the Vijayawada
corridor with simulated vehicles moving on it, and keeps a raw event log
alongside for debugging.

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
├── Makefile                 # make dev / make test / make lint / make down
├── contracts/                # ONE event language — shared by all services
│   └── events/*.avsc
├── packages/
│   ├── common/               # event bus client (Redis Streams now, Kafka later, ADR-003)
│   ├── domain/                # entities, value objects, state machines — safety-kernel types as of M2
│   └── geo/                   # homography, ground-plane projection — arrives M8
├── services/
│   ├── sim-service/          # [ARCH] services 3,4,5,17,19,20 — traffic state, control, adapters
│   │   └── sim_service/
│   │       ├── adapters/sumo/       # TraCI loop (M1)
│   │       ├── control/safety/      # L0 interlocks — pure predicates (M2)
│   │       ├── control/strategies/  # fixed_time (M2); webster/actuated (M3); camp (M4); acamp (M5)
│   │       ├── control/memory.py, tuning.py, online_calibration.py  # M5's learning layer
│   │       └── signal_controller/   # arbitration ladder + cabinet port (M2); +lane_cache, discharge_observer (M5)
│   ├── api-service/          # [ARCH] services 6,8-12,14,15 — incidents, dispatch, routing, corridor, config, audit
│   └── vision-service/       # [ARCH] services 7,18 — vision pipeline, camera ingestion
├── scenarios/                 # networks + demand for real/synthetic areas; suite/ (acceptance tests) arrives M2+
├── infra/postgres/           # PostGIS schema + road-network import script
├── cases/atlas.yaml          # the case atlas, machine-readable — arrives M2+
├── bench/                     # benchmark harness — arrives M3
├── notebooks/                 # calibration notebooks — arrives M8
├── scripts/                   # gate/benchmark/diagnostic scripts (M3-M5), one per experiment
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
| M5 | A-CA-MP (adaptive, with memory) | ✅ done — beats/ties Webster except heavy (~7% loss, open) |
| M6 | Incident → dispatch → routing | not started (by design — see README top) |
| M7 | Green corridor + anticipation + debt | not started (by design — see README top) |
| M8 | Vision on real footage | not started |
| M9 | Benchmark, evaluation, site | not started |

Full detail for each milestone (demo + gate) is in the build guide §7.
