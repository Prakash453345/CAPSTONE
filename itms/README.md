# ITMS — Intelligent Traffic Management & Emergency Response Platform

Capstone implementation, built milestone by milestone against `ITMS Build Guide` v1.0
(companion to `smart-traffic-platform-architecture.md` v1.1 and
`platform-architecture-diagram.mermaid`). Those three documents are the spec; this
repo is the build. Where this README and the docs disagree, the docs win — fix the
README.

## Current milestone

**M0 — Skeleton.** See `PROGRESS.md` for what's built and what's next.

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
it connects to the api-service WebSocket and prints every event it receives.

## Why it's built this way

The core architectural bet, from the architecture doc: **every data source is an
adapter behind a common event contract.** `contracts/events/` is that contract. All
services import from it; nothing hand-rolls its own event shape. This is cheap now
and expensive to retrofit later, so it exists from milestone zero even though only
one event type (`SystemHeartbeat`) is defined so far.

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
│   ├── domain/                # entities, value objects, state machines — arrives M2+
│   └── geo/                   # homography, ground-plane projection — arrives M8
├── services/
│   ├── sim-service/          # [ARCH] services 3,4,5,17,19,20 — traffic state, control, adapters
│   ├── api-service/          # [ARCH] services 6,8-12,14,15 — incidents, dispatch, routing, corridor, config, audit
│   └── vision-service/       # [ARCH] services 7,18 — vision pipeline, camera ingestion
├── scenarios/                 # executable acceptance tests — arrives M1+
├── cases/atlas.yaml          # the case atlas, machine-readable — arrives M2+
├── bench/                     # benchmark harness — arrives M3
├── notebooks/                 # calibration notebooks — arrives M8
└── web/                       # demo page — grows with each milestone
```

## Milestone map

| # | Milestone | Status |
|---|---|---|
| M0 | Skeleton | 🚧 in progress |
| M1 | SUMO adapter and traffic state | not started |
| M2 | Safety kernel (L0 interlocks) | not started |
| M3 | Baselines and KPI harness | not started |
| M4 | CA-MP Layer 1 | not started |
| M5 | Layer 2 coordination | not started |
| M6 | Incident → dispatch → routing | not started |
| M7 | Green corridor + anticipation + debt | not started |
| M8 | Vision on real footage | not started |
| M9 | Benchmark, evaluation, site | not started |

Full detail for each milestone (demo + gate) is in the build guide §7.
