# Progress log

One entry per milestone. This file is the source of truth for "what's actually
built" — keep it honest, including partial/deferred items.

## M0 — Skeleton

**Status:** built and gate verified. `sim-service` → Redis → `api-service` →
WebSocket confirmed working end to end (a WebSocket client connected to
`/v1/stream` and received live `SystemHeartbeat` events published by
`sim-service`). Lint (ruff), type check (mypy), and tests (pytest, including
the real-Redis integration test) all pass clean.

**What exists:**
- Repo layout matching build guide §6.
- `docker-compose.yml`: `postgres` (PostGIS + TimescaleDB extensions), `redis`, `minio`.
- `contracts/events/`: envelope schema + `SystemHeartbeat` (the one event this
  milestone needs). More event types arrive with the milestones that need them
  (M1 adds `VehiclePositionUpdated` / `ApproachState`, M2 adds `SignalChanged`, etc.)
  rather than all ~15 being stubbed out now with nothing to validate them against.
- `packages/common/itms_common`: `EventBus` protocol (ADR-003 — one interface,
  Redis Streams today, swappable for Kafka later without touching callers) and
  Avro-backed envelope (de)serialization.
- `services/sim-service`: publishes a `SystemHeartbeat` event once a second. Stands
  in for the TraCI loop that arrives in M1.
- `services/api-service`: FastAPI app. Consumes the bus, exposes `GET /health` and
  a `WS /v1/stream` that fans out every event it consumes as JSON.
- `web/index.html`: single static page, connects to `/v1/stream`, prints events as
  they arrive. Placeholder for the real dashboard build-out.
- `.github/workflows/ci.yml`: lint (ruff) + type (mypy) + test (pytest) on push.
- `Makefile`: `make dev`, `make test`, `make lint`, `make down`.

**Deferred to later milestones (intentionally, not forgotten):**
- Kafka is not wired up; Phase-1 uses Redis Streams per build guide §6.1 note.
- `packages/domain` and `packages/geo` are empty placeholders — first real content
  arrives in M2 (incident state machine) and M8 (homography) respectively.
- `vision-service` is an empty placeholder — arrives M8.
- `scenarios/`, `cases/atlas.yaml`, `bench/` exist as directories with a README
  each explaining what will land there and when — no content yet, nothing to test.
- MinIO/object storage is running in the compose stack but nothing writes to it
  yet (first writer is the vision service, M8, and camera ingestion frame refs).

**Gate (build guide M0):** "`make dev` works on a clean machine in under 10
minutes" + one end-to-end hello event. **Fully satisfied** — verified both in
the build environment (via a local Redis, since that sandbox can't reach
Docker Hub) and, separately, `make dev` itself run end-to-end on the actual
target machine with real Docker: images pulled, all three containers healthy,
`sim-service` + `api-service` up, heartbeat events visible live in the browser.

## M1 — SUMO adapter and traffic state

**Status:** in progress. Network built and verified; TraCI loop, event
emission, and the live dashboard map are not started yet.

**What exists:**
- `scenarios/networks/vijayawada/`: the real road network — MG Road corridor,
  Benz Circle to PNBS via Governorpet, 16 junctions (7 signal-controlled, 9
  priority), built from an actual OpenStreetMap extract. Fully reproducible
  via `build.sh`; see that directory's README for why this corridor, why not
  the whole city, and the exact pipeline (`osmGet.py` → filter by road name →
  `netconvert`).
- SUMO (1.27.1, via `pip install eclipse-sumo`) confirmed working both in the
  build environment and on the target machine.

**Not yet built:**
- The TraCI loop itself (`sim-service` driving the simulation and reading
  vehicle state).
- `VehiclePositionUpdated` / `ApproachState` event contracts and their
  publication onto the bus at 1 Hz.
- PostGIS import of the road network (currently only the SUMO `.net.xml`
  exists; the architecture doc's `road_segment` table has nothing in it yet).
- Demand (`scenarios/demand/*.rou.xml`) — no vehicles are generated yet, just
  the empty road network.
- Live vehicles on the dashboard map (`web/index.html` still only shows the
  M0 heartbeat).

**Gate (build guide M1):** "you can watch simulated traffic move on a real
map of your city, at 1 Hz, with no dropped ticks at 2× real time." Not yet
met — network is real and ready, simulation loop is the next piece.
