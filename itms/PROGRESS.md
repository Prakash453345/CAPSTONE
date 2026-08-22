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

## M3 — Baselines and KPI harness

**Status:** in progress. All three required baseline strategies (Webster
fixed-time, semi-actuated, coordinated-actuated) exist, are property- and
unit-tested, and have each been run end-to-end against the real 7-junction
Vijayawada corridor with zero interlock violations. The metrics collector,
10-seed statistical harness, and `make bench` report — the gate's literal
deliverable — are not yet built.

**What exists:**

- `sim_service/signal_controller/traci_cabinet.py` (`TraCICabinet`): the
  real `CabinetPort` implementation M2 deliberately deferred — backs the
  arbitration ladder onto a live TraCI connection instead of `FakeCabinet`.
  SUMO has no fault-injection surface at this layer, so C1-C5 stay proven
  once against `FakeCabinet` (M2) rather than re-proven per backend; that
  split is documented in the module's own docstring.
- `sim_service/control/runner.py` (`run_controlled_scenario`): drives a
  full SUMO run under the real arbiter/interlocks, handling the
  yellow → all-red → next-green sequencing the cabinet layer doesn't own.
  Widened twice this milestone: `StrategySource` accepts either one
  strategy for every junction (fixed-time's original shape) or a
  per-junction mapping (Webster, coordinated-actuated — each needs a
  different tuned plan per junction); an optional `link_lanes` parameter
  wires a live `ActuationDetector` per junction for demand-aware
  strategies (semi-actuated, coordinated-actuated).
- `scenarios/networks/vijayawada/extract_tier0_config.py`: extracts real
  `Tier0Config`s (phases, ring order, conflict matrix) from the corridor's
  own `.net.xml` — conflict data and phase structure are netconvert's real
  traffic-engineering output, not a hand approximation. `min_green_s` /
  `max_green_s` and per-junction `max_wait_s` are deliberate additions,
  fixed to principled safety-engineering constants after an earlier
  version wrongly took them from netconvert's own guessed fixed-time
  `duration` (see the module's docstring for the full account — this bug
  silently capped every tuning strategy in the project to netconvert's
  arbitrary ~39s regardless of measured demand).
- `scenarios/networks/vijayawada/measure_flows.py`: real per-link flow
  counts from the corridor's own route file, feeding Webster's tuning
  instead of an assumed/uniform flow.
- `scenarios/networks/vijayawada/link_lanes.py`: lane-granularity link map
  used by `ActuationDetector` to sample real lane occupancy per movement.
- `scenarios/networks/vijayawada/corridor_geometry.py`: real junction
  ordering and cumulative distance along the corridor, from the network's
  own UTM-projected coordinates (2D PCA along the dominant axis, not an
  assumed order) — feeds coordinated-actuated's progression offsets.
- `sim_service/signal_controller/detectors.py` (`ActuationDetector`): a
  loop-detector emulation (gap-timeout presence + a separate service-reset
  wait clock) standing in for real vehicle detectors, used by
  semi-actuated and coordinated-actuated.
- `sim_service/control/strategies/`:
  - `fixed_time.py` — M2's ring-at-min-green-floor strategy, now actually
    driving the real corridor via `TraCICabinet`.
  - `webster.py` — Webster's 1958 delay-minimizing cycle/split formula
    (`compute_timing`), computed from real measured flows per junction,
    not guessed. Accepts an optional `fixed_cycle_s` (added for
    coordinated-actuated) to compute a proportional split within an
    externally-fixed shared cycle instead of its own optimum.
  - `semi_actuated.py` — major phase on continuous recall, minor phases
    actuated with longest-wait priority among calls.
  - `coordinated_actuated.py` — a shared corridor-wide cycle (set by the
    most-saturated junction), per-junction travel-time offsets for
    green-wave progression, a guaranteed coordinated window with a hard
    force-off deadline for minor phases.
- `scripts/smoke_m3_*.py`: one real end-to-end SUMO smoke test per
  strategy against the actual 7-junction network (not part of the pytest
  suite — each shells out to a real SUMO process).

**Bugs found and fixed this milestone** (every one found by running the
real 7-junction network end-to-end, *not* by the Hypothesis property
suites, which passed cleanly throughout — property tests alone did not
catch config-parameter-relationship bugs; real-data verification did):

1. `min_green_s`/`max_green_s` taken directly from netconvert's guessed
   fixed-time `duration`, defeating any real tuning (see
   `extract_tier0_config.py` above). Fixed with documented fixed safety
   constants (10.0s / 90.0s), chosen over the alternative after an
   explicit check-in on which approach to take.
2. The `ActuationDetector`'s wait clock never reset for a continuously-
   busy lane, even while it was being actively served — eventually
   tripped I5 on a heavily-trafficked movement that *was* being served
   regularly. Fixed by resetting the wait clock for any currently-served
   movement regardless of occupancy.
3. A per-junction blanket `max_wait_s` default was structurally too small
   for a 4-phase ring's own `max_green_s` ceiling, legitimately starving a
   minor movement. Fixed by scaling `max_wait_s` per junction to that
   ring's own worst-case full-rotation time.
4. Coordinated-actuated's raw Webster split could leave the coordinated
   phase so large that other phases structurally could not fit their own
   `min_green_s` + clearance inside the remaining cycle — permanently
   starving a minor phase (observed: one phase held green 262+ seconds
   straight). Fixed by capping `coordinated_green_s` in
   `build_corridor_plan` to guarantee room for every other phase's bare
   structural minimum, plus a 5-second margin against exact-boundary /
   discretization risk at 1 Hz tick granularity.

**Known, accepted limitation (not a bug):** one of the 7 real junctions
(`cluster_1880441740_4393296791`, 4 phases) has no room left in the
54.8s shared corridor cycle for its own coordinated window once its other
3 phases' bare structural minimum (3 × (10s min_green + 8s clearance) =
54s) is reserved — `build_corridor_plan` correctly clamps its
`coordinated_green_s` to 0. This junction still runs completely safely
(zero interlock violations there specifically); it just runs like
semi-actuated instead of getting a green-wave window, because more-phase
junctions structurally cannot share a cycle length tuned for their
simpler neighbours without either running non-coordinated or lengthening
the cycle for everyone. This is standard practice on real coordinated
corridors (not every intersection along a coordinated corridor is
"coordinated"), and lengthening the shared cycle to accommodate it would
very likely increase average delay at the other six, already
well-tuned junctions — a worse trade made without any actual benchmark
data to justify it. Revisit only if the M3 metrics collector (not yet
built) shows this junction as a measurable outlier.

**Honest single-seed comparison** (seed=1, not yet the required 10-seed
statistical comparison — see Not yet built):

| Strategy | avg wait (s) | avg trip duration (s) |
|---|---|---|
| fixed-time (M2, untuned) | 113.4 | 268.9 |
| Webster (tuned) | 60.1 | 208.5 |
| semi-actuated | 204.0 | 373.1 |
| coordinated-actuated | 74.4 | 220.5 |

Webster wins outright on this seed — plausible, since the corridor's
demand is currently uniform-random rather than the directionally-skewed,
platoon-forming traffic that semi-actuated's "dominant major street"
assumption and coordinated-actuated's green-wave progression are designed
to exploit (see `scenarios/demand/vijayawada/README.md`: the demand is
explicitly placeholder, not calibrated). This is a real, reportable
finding, not a bug — it will be revisited once real turning-movement
demand exists and once the 10-seed harness replaces a single seed.

**Verification:**

- `ruff check .` and `mypy packages services infra scenarios` clean
  throughout.
- 56 tests passing (Hypothesis property suites per strategy — each
  threading demand/wait state realistically across ticks rather than
  redrawing it independently per tick, which would manufacture physically
  impossible states — plus deterministic mechanics tests and
  `corridor_geometry`'s hand-checkable synthetic-geometry tests).
- Each strategy run end-to-end against the real 7-junction corridor for
  the full 1800s scenario: zero interlock violations, zero fault events,
  in all four cases (fixed-time, Webster, semi-actuated,
  coordinated-actuated).

**Not yet built:**

- The metrics collector: person-delay (occupancy-weighted — the current
  corridor demand is single-vType `veh_passenger` only, so this needs
  either a documented proxy or a heterogeneous vType mix with stated
  occupancy assumptions before "person-delay" is more than relabeled
  vehicle-delay), person-throughput, max per-approach wait (distribution,
  not just mean), stops per vehicle, queue-spillback events.
- The 10-seed statistical harness with confidence intervals (paired
  across controllers on the same seed set), and the `make bench` target
  that produces the gate's comparison table.
- `SignalChanged`/`SignalFaulted` are still not published onto the event
  bus from a live run (flagged as M3's job in the M2 section above) —
  the smoke scripts and `run_controlled_scenario` don't wire a producer
  yet.

**Gate (build guide M3):** "you can run `make bench` and get a table of
person-delay, throughput, max-wait, and stops for three baseline
controllers over 10 seeds with confidence intervals." **Not yet
satisfied** — the three baselines are tuned, safe, and verified
end-to-end; the metrics collector and bench harness that turn that into
the gate's actual table are the remaining work.
