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

**Status:** built and gate verified. SUMO/TraCI drives the real Vijayawada
corridor scenario, publishes `VehiclePositionUpdated` / `ApproachState` at
1 Hz onto Redis Streams, `api-service` fans them out over the WebSocket, and
`web/index.html` renders them as moving vehicles on a real map. Lint, type
check, and tests all pass clean; the full pipeline (SUMO → Redis →
api-service → WebSocket → browser) was verified live, not just unit-tested.

**What exists:**
- `scenarios/networks/vijayawada/`: the real road network — MG Road corridor,
  Benz Circle to PNBS via Governorpet, 16 junctions (7 signal-controlled, 9
  priority), built from an actual OpenStreetMap extract. Fully reproducible
  via `build.sh`.
- `scenarios/demand/vijayawada/`: 708 vehicles over a 30-minute window (seed
  42), generated via `randomTrips.py` + `duarouter`. Explicitly **not**
  calibrated OD demand — enough to demonstrate the gate, not enough to draw
  real conclusions from. Real calibration is build guide §8.5, deferred to
  M8.5.
- `contracts/events/vehicle_position_updated.avsc` and `approach_state.avsc`:
  new event types for this milestone. Both are documented as simplified —
  `approach_state`'s `q_pcu` is a raw vehicle count (not PCU-weighted) and
  `movement_id` holds a SUMO edge id (not a real movement group); a breaking
  schema change is expected when CA-MP (M4) and vision (M8) land the real
  versions.
- `services/sim-service/sim_service/adapters/sumo/traci_loop.py`: the TraCI
  loop. Steps the simulation, reads every vehicle's position and every
  edge's occupancy each tick, publishes both event types, and measures
  dropped ticks against the wall-clock budget implied by
  `SIM_REALTIME_FACTOR`. `sim_service/main.py` runs this by default now
  (`SIM_MODE=sumo`); the M0 heartbeat loop still exists
  (`SIM_MODE=heartbeat`) for bus-plumbing sanity checks.
- `packages/common/itms_common.RedisStreamsSyncBus`: sync producer client
  for the TraCI loop, which is itself synchronous (blocks on SUMO subprocess
  IPC every step). Same wire format as the async `RedisStreamsBus` — one bus
  contract, two transport-side clients (ADR-003).
- `infra/postgres/import_road_network.py` +
  `infra/postgres/init/002_road_network.sql`: PostGIS import. `road_edge`
  (LineString) and `road_junction` (Point) tables, keyed by
  `(network_name, sumo_*_id)`, upserted from
  `scenarios/networks/vijayawada/export_geojson.py`'s output. Verified
  end-to-end against a real Postgres+PostGIS instance: 33 edges + 25
  junctions imported with correct real-world coordinates, re-running is a
  clean no-op (idempotent upsert, no duplicate rows).
- `web/index.html`: now a live map (Leaflet, vendored locally under
  `web/vendor/leaflet/` — not loaded from a CDN, so it also works offline).
  Shows the road network, traffic-light junctions, and vehicles moving in
  real time from `VehiclePositionUpdated`; edge color darkens with
  occupancy from `ApproachState`. Raw event log kept alongside as a side
  panel for debugging. Verified visually with a headless-browser screenshot
  while a live sim run was in progress — vehicle markers moved and the
  event/vehicle counters climbed correctly.

**Bug found and fixed while verifying this milestone:** `RedisStreamsBus.subscribe`
only created its Redis consumer group once, before entering its read loop.
If the group ever disappeared out from under a long-running consumer (Redis
restart with no persistence, a stream deleted and recreated) the next
`XREADGROUP` raised `NOGROUP` and killed the consumer task silently —
asyncio only logs "Task exception was never retrieved," easy to miss, and
the dashboard just goes quiet with no visible error. Fixed by catching
`NOGROUP` and recreating the group inline before continuing the read loop.

**Not yet built:**
- Viewport filtering (ARCH §7.2) on the WebSocket fan-out — deliberately
  deferred; documented in `api_service/main.py`'s module docstring. This
  network is small enough that broadcasting every event to every client is
  still cheap. Revisit when that stops being true.
- Vehicle *departure* isn't an event on the bus yet (SUMO doesn't get asked
  to emit one at M1 scope) — the dashboard infers it client-side by sweeping
  markers that haven't been updated in 5s. Fine for now; a real
  `VehicleDeparted`-style event is a natural M2+ addition if something
  server-side ever needs to know too.

**Gate (build guide M1):** "you can watch simulated traffic move on a real
map of your city, at 1 Hz, with no dropped ticks at 2× real time." **Fully
satisfied** — verified with a 120-step (2 minutes sim time) run at
`SIM_REALTIME_FACTOR=2.0`: 0 dropped ticks. Separately verified the event
pipeline end-to-end with a real WebSocket client and, visually, in a
headless browser against the live map.

## M2 — Safety kernel

**Status:** built and gate verified. Layer 0 interlocks, the arbitration
ladder, a fault-injectable fake cabinet, and the fixed-time fallback
strategy all exist and are tested — the property suite at the guide's
exact bar (10,000 generated cases per invariant) and the C1-C5
fault-injection tests, all green.

**What exists:**
- `packages/domain/itms_domain/signal.py`: the pure value types the kernel
  runs on — `SignalPlan`, `PlanStep`, `JunctionContext`, `Tier0Config`,
  `Phase`, `Violation`. No I/O, no clock reads (time is always a parameter)
  — deliberate, since it's what lets the exact same code run inside the
  live controller and inside a property test. Junction geometry (movements,
  conflict matrices, ring order) is modeled generically rather than mapped
  onto the 7 real signal-controlled junctions in the Vijayawada network —
  see `interlocks.py`'s module docstring for why that mapping is scoped to
  M3, not M2.
- `services/sim-service/sim_service/control/safety/interlocks.py`: `check()`
  and its 8 predicates — `no_conflicting_greens` (I1), `min_green_satisfied`
  (I3), `clearance_intervals_present` (I2), `pedestrian_clearance_respected`
  (I4), `max_wait_not_exceeded` (I5), `preempt_budget_ok` (Tier-0 config
  guard, not itself a numbered invariant), `phase_reachable` (I6),
  `transition_legal` (structural, likewise not numbered). I7 ("commanded
  state and read-back state converge, or commanding stops") is deliberately
  not here — it's a property of a live command sequence over time, not a
  single proposed plan, so it lives in the arbiter's cabinet reconciliation
  instead.
- `services/sim-service/sim_service/control/strategies/fixed_time.py`:
  arbitration-ladder rung 5. Cycles the ring at each phase's own
  `min_green_s` — explicitly **not** the "properly tuned Webster... compute
  optimal cycle from measured flows" strategy build guide §7 asks for as an
  M3 baseline. What M2 needs from it is narrower: always interlock-safe by
  construction, demand-blind, available even with zero sensor state.
  Property-tested driving thousands of randomized ring configurations
  through `interlocks.check()` with zero violations, including routing
  around a faulted phase (C1) and the all-phases-faulted case (drops to no
  plan rather than inventing one).
- `services/sim-service/sim_service/signal_controller/`: `cabinet.py`
  (`CabinetPort` protocol + `FakeCabinet`, fault-injectable) and
  `arbiter.py` (`tick()` — the priority ladder `[ARCH §2.2]`: hardware
  faults → manual override → corridor preemption → optimizer → fixed-time.
  M2 only has a real requester for rung 5; rungs 2-4 are absent, not
  stubbed, until M4/M6/M7 give them one). `tick()` reconciles cabinet state
  every call (I7) before proposing or committing anything.
- `contracts/events/signal_changed.avsc` / `signal_faulted.avsc`: new event
  types, payload shape verified to round-trip through
  `itms_common.encode_envelope`/`decode_envelope` and to match
  `arbiter.Decision.events` exactly. **Not yet published onto the bus** —
  M2's job was the kernel and ladder in isolation against a fake cabinet;
  wiring a real producer into the running simulation is M3's job (see
  `arbiter.py`'s docstring).

**Verification:**
- `pytest services/sim-service/tests/control/safety/test_interlocks_properties.py`:
  9 Hypothesis property tests, `max_examples=10_000` each (90,000 generated
  cases total, ~49s). Each test plays "a deliberately malicious test
  strategy" — constructs a plan engineered to violate exactly one invariant
  and asserts `check()` catches it, *and* that a corresponding legal plan is
  never falsely flagged. Confirms the M2 gate's own wording: proposals from
  an adversarial generator cannot produce a conflicting green (I1) or any
  other interlock violation.
- `pytest services/sim-service/tests/signal_controller/test_fault_injection.py`:
  C1 (lamp failure, routes around it; all-phases-faulted drops to failsafe),
  C2 (conflict monitor trip — observed, never fought), C3 (comms loss, both
  on the read and the command side — stops commanding), C4 (power restart —
  forced all-red, then a clean defined resume, never an assumed phase), C5
  (command/readback divergence — halts commanding). All reach a documented,
  asserted safe state.
- Full repo lint (ruff) + type check (mypy, now also covering
  `packages/domain`) + test suite (24 tests total) all pass clean.

**Not yet built:**
- No real requesters for ladder rungs 2-4 (manual override, corridor
  preemption, adaptive optimizer) — arrive with M6, M6/M7, and M4
  respectively.
- The arbiter isn't wired to the live Vijayawada corridor simulation yet —
  it runs against `FakeCabinet` only. A real `CabinetPort` implementation
  driving SUMO's actual traffic lights via TraCI, and `SignalChanged`/
  `SignalFaulted` actually being published onto the bus, are scoped to M3
  (the baseline strategies are the first thing that needs to actually move
  real, if simulated, signals).
- C6-C10 (optimiser-silent fallback, bad Tier-0 config rejection, clock
  skew, leader failover, split-brain) are not covered yet — C6/C7 fit
  naturally once M3's KPI harness runs a live optimizer-silence scenario;
  C8-C10 are distributed-systems concerns (multiple controller instances,
  fencing epochs) that don't apply to this single-process build yet.
- Dual-control governance for Tier-0 config changes (`safety_config.parameter`,
  ARCH §5.2 — proposed/approved by two distinct operators, staged rollout)
  is real production machinery this build doesn't implement: there's no
  operator/auth service yet to approve against (same M6/M7 boundary noted
  in api-service's M1 docstring for viewport filtering/auth). `Tier0Config.validate()`
  implements C7's "bad value rejected, last-known-good retained" as a plain
  function instead.

**Gate (build guide M2):** "the property suite passes with 10 000 generated
cases per invariant, and the fault-injection tests (C1–C5) all reach a
defined safe state. `SignalPlan` proposals from a deliberately malicious
test strategy cannot produce a conflicting green." **Fully satisfied** —
see Verification above.
