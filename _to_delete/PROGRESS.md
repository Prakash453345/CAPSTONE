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

**Update — metrics collector, vehicle mix, and the bench harness now
exist:**

- `scenarios/demand/vijayawada/assign_vtypes.py`: reassigns the
  corridor's 708 vehicles across four vTypes (motorcycle 35%, car 40%,
  auto-rickshaw 20%, bus 5%) by a seeded weighted draw, without touching
  any route or depart time. Occupancy per vType (1.3 / 1.5 / 2.5 / 40.0
  persons) is stored as a `<param>` on the vType itself. Mix shares and
  occupancy figures are commonly-cited approximations for a mixed Indian
  urban arterial, **not measured for this corridor** — same honesty
  level the demand's own README already applies to trip generation.
  vClass physical dynamics are left at SUMO's own defaults per class, not
  invented; all four classes are permitted on every lane of this network,
  so no vehicle's route changed and no Webster/coordination tuning needed
  redoing.
- `sim_service/control/metrics.py`: parses a run's `--tripinfo-output`
  plus the route file's vType occupancy into person-delay (SUMO's own
  per-vehicle `timeLoss`, occupancy-weighted), person-throughput,
  a wait-time **distribution** (mean/p50/p95/p99/max, not just a mean),
  and stops per vehicle. First 600s of departures excluded from
  delay/wait/stops (network still filling); throughput is deliberately
  not warm-up-filtered (see the module's own docstring for why).
- `sim_service/control/bench_stats.py`: dependency-free 95% confidence
  intervals using the correct Student's t critical value for small N
  (2.262 at the gate's own N=10, not the normal distribution's 1.96,
  which understates the interval by ~15% at this sample size).
- `scripts/bench.py` / `make bench`: runs the three tuned baselines
  (Webster, semi-actuated, coordinated-actuated) over the same fixed
  10-seed set each (paired comparison, §8.2), scores every run, and
  prints the table below. Raw per-seed numbers are written to
  `scripts/bench_results.json`, checked in alongside the seed list itself
  as the fixed workload manifest.

**The M3 gate table** (10 seeds each, mean ± 95% CI; all 30 runs: zero
interlock violations, zero fault events):

| controller | person-delay (person-s) | throughput (persons/h) | max-wait p95 (s) | stops/vehicle |
|---|---|---|---|---|
| Webster (tuned) | 190,234 ± 8,953 | 5,203.2 ± 0.0 | 167.4 ± 16.6 | 3.0 ± 0.2 |
| semi-actuated | 629,350 ± 27,442 | 5,203.2 ± 0.0 | 670.5 ± 34.6 | 6.1 ± 0.2 |
| coordinated-actuated | 203,200 ± 3,790 | 5,203.2 ± 0.0 | 216.8 ± 14.5 | 2.9 ± 0.1 |

Confirms the single-seed finding from earlier in this milestone, now with
real statistical backing: semi-actuated is decisively worse on this
demand (over 3x the person-delay, over 3x the p95 wait). Webster edges
out coordinated-actuated on person-delay and wait — plausible, since the
current demand is still uncalibrated uniform-random rather than the
directionally-skewed platooning traffic coordination is built to exploit
— but coordinated-actuated has the *fewest* stops per vehicle of all
three, a real and expected signature of progression (fewer stop-and-go
events even when total delay isn't the lowest). A genuine, reportable
trade-off, not a wash.

**Two honest caveats about this table, found while building it, not
smoothed over:**

1. **Person-throughput came out numerically identical (5,203.2 ± 0.0)
   across every controller and every seed.** This is a real property of
   the current experimental setup, not a bug: the corridor demand is a
   *fixed* trip list (same 708 vehicles, same depart times, same routes
   in every run) — `--seed` only perturbs SUMO's internal car-following/
   lane-changing randomness, not which trips exist. Combined with SUMO's
   300s forced-teleport (which prevents true permanent gridlock), every
   one of the same 708 vehicles eventually arrives under all three
   controllers, on every seed — so total persons served is a constant of
   the demand file, not a signal of controller quality. The build guide's
   own reasoning for including throughput at all ("pairs with delay;
   delay alone can be gamed by holding vehicles outside the network")
   doesn't get exercised by this scenario, because nothing in it is
   capable of actually stranding vehicles outside the network. It would
   become a real, discriminating metric either once demand is
   heavy/calibrated enough to saturate the network, or by measuring
   throughput over a shorter rolling window instead of the whole
   scenario. Reported as-is rather than hidden or re-defined to look more
   interesting than it is.
2. **A handful of simulated vehicle-vehicle collisions/teleports appeared
   during the bench runs** (SUMO's own car-following model occasionally
   producing a negative gap between two vehicles, e.g. a motorcycle and a
   car, followed by a forced teleport) — more frequently than with the
   original all-`veh_passenger` fleet. This is a SUMO microscopic-model
   artifact of introducing heterogeneous vehicle dynamics without also
   re-tuning car-following parameters for a mixed fleet, not a signal
   controller issue (I1-I7 interlocks, which govern signal-phase
   legality, are unaffected — zero interlock violations were recorded in
   every one of the 30 runs). Worth a closer look before this demand mix
   is relied on for anything beyond the M3 comparison it was built for.

**Gate (build guide M3):** "you can run `make bench` and get a table of
person-delay, throughput, max-wait, and stops for three baseline
controllers over 10 seeds with confidence intervals." **Satisfied** —
see the table above; `make bench` reproduces it end-to-end.

**Two remaining M3 loose ends, now closed:**

- `sim_service/signal_controller/spillback.py` (`SpillbackTracker`):
  counts queue-spillback episodes (§8.1: "count of link-full episodes") —
  a rising-edge count per lane crossing a 90% TraCI occupancy threshold,
  over every controlled junction's approach lanes. Wired into
  `run_controlled_scenario` as an optional `spillback_lane_ids` parameter
  (off by default — existing callers unaffected); the result dict now
  carries `spillback_events`. Verified against the real corridor for both
  fixed-time and semi-actuated: **zero spillback episodes on either**,
  consistent with (and explained by) the same finding as the
  person-throughput caveat above — the current demand simply isn't heavy
  enough to saturate any lane to 90%+ occupancy under any baseline,
  including the worst-performing one. Not a bug in the tracker (5 unit
  tests with a mocked occupancy sequence confirm the rising-edge counting
  logic directly); a real property of this demand level, honestly
  reported rather than tuned to produce a more interesting number.
- `control/runner.py`'s optional `bus` parameter: every `arbiter.tick()`
  decision is now published as a real `SignalChanged`/`SignalFaulted`
  event, through the same `RedisStreamsSyncBus`/`encode_envelope` path
  `traci_loop.py`'s live dashboard producer already uses (ADR-003 — one
  bus contract, same wire format). Topics: `signal.changed` (named in
  ARCH §6.2's own table) and `signal.faulted` (not named there explicitly
  — inferred from the same `signal.<verb>` convention `signal.changed`/
  `signal.override.*` follow, documented as an inference in both the
  module docstring and the `.avsc` files rather than presented as
  something the architecture doc actually specifies). Off by default —
  the M3 smoke scripts and `scripts/bench.py` don't pass a bus, since a
  30-run bench sweep publishing to a bus nothing is consuming would just
  be noise, not a behaviour change for any existing caller.
  `test_signal_events.py` proves the payload shape round-trips through
  the real `contracts/events/*.avsc` schemas (a gap PROGRESS.md's M2
  section had claimed was already "verified" without an actual checked-in
  test); `test_runner_bus_integration.py` proves the wiring fires for
  real — a live SUMO run whose published events are read back off a real
  Redis stream and decoded, not just asserted in isolation. Both new test
  files, plus `test_spillback.py`, bring the suite to 82 tests (80 run by
  default, 2 integration tests gated behind `RUN_INTEGRATION_TESTS=1` +
  a reachable Redis, same convention `packages/common`'s existing
  integration test already established).

M3 is now fully closed out: three tuned, safe, benchmarked baselines; the
gate table; and both loose ends that had been carried since M2.

## M4 — CA-MP (Corridor-Anticipatory Max-Pressure), Layer 1 — in progress

**What exists:**

- `packages/domain/itms_domain/signal.py`: additive-only extension.
  `JunctionContext` gained `queue_pcu`/`receiving_occupancy`/`confidence`
  (all default empty, same non-breaking pattern `has_demand`/
  `wait_times_s` set before them); `Tier0Config` gained `sat_flow_pcu_s`
  (default empty). Every M2/M3 strategy is provably unaffected — full
  suite passed unchanged right after this change.
- `sim_service/control/strategies/camp.py`: the algorithm itself —
  `pressure(p) = P_flow(p) − P_block(p) + F(p) − S(p)` (build guide
  §3.4's Terms 1, 2, 3, 6; Terms 4/5 — corridor anticipation and debt
  recovery — are explicitly Contribution 1, deferred to M7 once the
  Green Corridor Engine can supply real reservations), cyclic ring
  selection with hysteresis/skip/k-lookahead (§3.7), and a real
  degradation-ladder `select_mode` (§3.8) that only has two behaviourally
  real branches in this build — full CA-MP, or fall back to the
  property-tested-safe `fixed_time` — because nothing before M8 can ever
  produce a real movement confidence below 1.0.
  - **A resolved ambiguity, documented rather than silently picked**: the
    guide's prose defines the blocking term's queue as `q_m`, "queue on
    the receiving link" — a different quantity from Term 1's own upstream
    queue `q_l`. The guide's own §4 reference implementation, though,
    reuses the identical `q_pcu` field for both terms. This build follows
    the code, not the prose, for the reason spelled out in `camp.py`'s
    own module docstring: inventing a second per-movement "downstream
    queue" concept would mean guessing at data no extraction script in
    this project has ever computed. One real, load-bearing consequence
    of that choice, worth stating plainly: at zero receiving-link
    occupancy (`θ_m == 1`), the flow and block terms cancel **exactly**,
    for every movement, regardless of queue size — so in free flow
    (nothing downstream congested yet), phase selection is driven
    entirely by wait-time fairness, not raw queue length. This is a real
    property of the algorithm as specified, not a bug; it matters for
    the θ_m ablation the M4 gate requires (see Not yet built).
  - **A bug caught before it shipped**: my own first test for "advances
    to the highest-pressure candidate" assumed bigger queue always wins,
    which is exactly the case the paragraph above rules out at zero
    occupancy. Caught by actually running the test, not by inspection —
    fixed by differentiating the test scenario via wait time instead.
- `sim_service/signal_controller/queue_state.py` (new): the live sampler
  CA-MP needs before it can see anything but empty defaults —
  `QueueStateSampler.sample()` returns real `(queue_pcu,
  receiving_occupancy)` from TraCI every tick. `queue_pcu[l]` is
  build guide §3.2.1's observed term: the PCU-weighted count of vehicles
  actually **stopped** (speed < 0.1 m/s, SUMO's own halting-speed
  convention) on movement `l`'s approach lane, weighted by each vehicle's
  own vType PCU value. `receiving_occupancy[l]` is `ρ_m`: the downstream
  lane's live occupancy fraction, reusing the exact query
  `SpillbackTracker` already uses, pointed at each movement's own
  receiving lane via a new `link_lanes.link_to_receiving_lane_map()`
  (same `<connection>` parse as the existing upstream map, reading
  `to`/`toLane` instead of `from`/`fromLane`).
  - `assign_vtypes.py` gained a `<param key="pcu">` alongside the
    existing `occupancy` param on each vType — IRC SP:41's indicative
    prior (two-wheeler 0.3, auto-rickshaw 0.6, car 1.0, bus 3.0), the
    same not-measured-for-this-corridor caveat as MIX/OCCUPANCY.
    Regenerated `vijayawada_corridor.rou.xml` in place; vehicle
    type/route/depart assignment is unchanged (same seed, same mix
    logic — only the new param was added).
  - `extract_tier0_config.py` now populates `Tier0Config.sat_flow_pcu_s`
    for every real movement in the corridor, but **with a single
    conventional placeholder value (0.5 PCU/s/lane ≈ 1800 PCU/h), not a
    measured one** — the build guide is explicit that saturation flow
    must be measured per approach ("do not use a manual value," §8.5),
    and this project has no discharge-headway field data yet. Flagged
    here as a limitation to close before any CA-MP result is presented
    as more than a software-correctness demonstration.
- `sim_service/control/runner.py`: `run_controlled_scenario` gained two
  more optional, additive parameters — `receiving_lanes` and
  `vtype_pcu` — which, together with the existing `link_lanes`, wire a
  `QueueStateSampler` per junction and merge its output into the same
  `JunctionContext` rebuild `ActuationDetector` already feeds. Both
  default to `None`; every M2/M3 caller is unaffected.
- `scripts/smoke_m4_camp_runner.py` (new): CA-MP driving all 7 real
  junctions of the corridor, real PCU-weighted queues and real receiving
  occupancy from live TraCI state, `nominal_cycle_s` per junction taken
  from Webster's own tuned cycle (tying the duration heuristic to
  already-measured flow data rather than a second invented constant).
  **Result: 2406 steps, zero interlock violations, zero fault events,
  zero spillback episodes** — consistent with (not contradicting) M3's
  own finding that current demand on this corridor isn't heavy enough to
  jam any lane solid under any controller tested so far.

**Verification:**

- `test_camp.py`: 26 tests — `select_mode` unit tests, a degraded-
  confidence-falls-back-to-fixed_time test, hand-checked pressure-term
  unit tests (flow/block/fairness/switch, including the zero-occupancy
  cancellation case above), ring-candidate/skippability unit tests, two
  Hypothesis property tests (general interlock-safety over many ticks,
  and fault-routing around a faulted phase — 300 and 200 examples), an
  all-phases-faulted edge case, and five deterministic mechanics tests
  (extend-below-min-green, advance-once-maxed-out, hysteresis, and both
  `_allocate_green` fallback/clamp cases).
- `test_queue_state.py`: 11 tests — PCU-weighted halted-vehicle counting,
  the halting-speed boundary (strictly less-than, not ≤), unknown-vtype
  default, empty-lane, receiving-occupancy-reads-the-downstream-lane (not
  the approach lane), a link with no receiving-lane entry, independence
  across multiple links, and `load_vtype_pcu`'s own file-parsing (synthetic
  fixtures plus one test read straight off the real checked-in corridor
  route file).
- `ruff`, `mypy`, and the full pytest suite (117 passed, 2 skipped — the
  2 integration tests, same as before) all clean after every change in
  this section, not just at the end.
- `scripts/smoke_m4_camp_runner.py` run against the real corridor: PASS
  (see above).

**Update — 3 demand levels built and CA-MP proven safe at all of them:**

- `build.sh` gained two optional positional args (`period`, `suffix`),
  defaulting to the original medium invocation exactly (`./build.sh` with
  no args reproduces the checked-in medium file byte-for-byte) — every
  earlier milestone's dependency on the plain invocation is unaffected.
  `build_demand_levels.sh` (new) calls it twice more: LIGHT (period 5.0,
  360 vehicles) and HEAVY (period 1.25, 1440 vehicles) as separate
  `vijayawada_corridor_light.rou.xml`/`_heavy.rou.xml` files (plus
  matching `.sumocfg`s), never touching the medium file. The 0.5x/2x
  spread around medium's 708 vehicles is a plain volume choice, not
  derived from any measured capacity (this corridor still has no
  calibrated saturation point) — three genuinely different, ordered
  congestion levels to compare, not levels picked to flatter a result.
  `assign_vtypes.py`'s `__main__` now takes an optional path argument so
  the same seeded vType-mix logic runs against light/heavy too.
- `smoke_m4_camp_runner.py` gained an optional demand-suffix CLI arg
  (`_light`/`_heavy`) and now measures flows from *that* demand level's
  own route file for Webster tuning (`compute_link_flows(net_path,
  route_path)`, not the medium default) — each demand level gets its own
  correctly-scaled `nominal_cycle_s`, not medium's cycle reused
  elsewhere.
- **Ran CA-MP end-to-end against the real corridor at all 3 levels.**
  Light: 2295 steps, 0 interlock violations, 0 fault events, 0 spillback
  episodes. Medium: 2406 steps, 0/0/0 (see above). Heavy: 3178 steps, 0
  interlock violations, 0 fault events, **0 spillback episodes** — CA-MP
  stays safe at 2x medium demand, but a genuinely worth-stating finding:
  even heavy demand didn't push any of the 7 junctions' own approach
  lanes to the 90%-occupancy spillback threshold, despite SUMO's own
  teleport log showing real congestion forming elsewhere on the network
  (`"waited too long (jam)"` warnings appear only under heavy). That
  congestion is happening off the specific lanes this build instruments,
  not proof CA-MP's blocking term did anything yet — consistent with,
  not contradicting, the zero-occupancy-cancellation property `camp.py`'s
  docstring already flags. It confirms rather than removes the need for
  a deliberately-engineered bottleneck (next) rather than "just add more
  demand" to ever exercise θ_m for real.

**Update — the θ_m ablation is built and run, and it surfaced a real
runner-level bug (found, fixed, verified) plus a genuine, dramatic
finding for the blocking term:**

- `run_controlled_scenario` gained `bottleneck_lane_speeds_mps` (another
  additive, `None`-by-default parameter): applies `traci.lane.setMaxSpeed`
  to named lanes once at scenario start, to engineer a downstream capacity
  reduction on purpose rather than hoping demand finds one (see the last
  update's finding that it doesn't, on this corridor, at any demand level
  tested). `camp.py`'s `CampConfig` gained `enable_blocking: bool = True`,
  an ablation switch that zeroes Term 2 entirely inside the *same*
  `pressure()` codepath (not a second hand-maintained copy) — the M4
  gate's own required "with vs. without θ_m" comparison needs exactly
  this, and nothing else in the build reads or sets it.
- `scripts/m4_bottleneck_ablation.py` (new): picks the single busiest
  measured movement under heavy demand, throttles every lane of its real
  receiving edge to a crawl (2.0 m/s), and runs 2×2 = 4 arms (blocking
  on/off × bottleneck on/off), same seed and heavy demand throughout,
  comparing person-delay, trips completed, and a spillback count scoped
  to just the bottleneck's own lanes.
- **A real bug the first full run found**: `cluster_1880441740_4393296791`
  (the same 4-phase junction flagged back in M3 as structurally tight —
  its bare minimum barely fits its own cycle) hit
  `failsafe_interlock_rejected` under the blocking-disabled arm, and
  *never recovered* — thousands of consecutive rejections for the rest of
  the run. Root cause, confirmed by direct diagnosis (see `runner.py`'s
  own `_recover_from_fault` docstring for the full chain): every failsafe
  branch commanded all-red and left `JunctionContext` completely
  untouched; `TraCICabinet` can't map an all-red raw state back to any
  known phase, so the divergence check never re-fires, the *same* frozen
  `current_phase_id`/`current_phase_elapsed_s` gets re-proposed forever,
  other movements' real (still-live) wait times climb without bound, and
  I5 rejects every subsequent proposal too — a permanent lock, not a
  transient one. This is a **runner-level gap, not specific to CA-MP** —
  any strategy could in principle trigger it; CA-MP's more adaptive
  proposals under engineered stress are just what first exposed it.
  **Fixed**: `_recover_from_fault` now re-commands the ring's first phase
  and resets elapsed time to 0.0 whenever a junction takes any non-nominal
  branch, mirroring the exact "defined resume, not an assumed one"
  precedent the scenario's own startup code already uses. 2 new unit
  tests (`test_runner_fault_recovery.py`, using `FakeCabinet` — no SUMO
  needed) confirm it. Full suite: 120 passed, 2 skipped.
- **The ablation result, run to completion after the fix** (heavy demand,
  1440 vehicles, capped at 3600 steps — see below for why):

  | arm                          | delay_s   | trips completed | interlock violations |
  |-------------------------------|-----------|------------------|-----------------------|
  | blocking on, bottleneck on   | 2,199,714 | 1439 / 1440      | 0                     |
  | blocking off, bottleneck on  |   807,988 | 1177 / 1440      | 2525                  |
  | blocking on, bottleneck off  | 1,634,273 | 1440 / 1440      | 0                     |
  | blocking off, bottleneck off |   938,369 | 1193 / 1440      | 2201                  |

  With blocking enabled, zero interlock violations in both conditions and
  essentially every vehicle completes its trip. With blocking disabled,
  thousands of interlock violations **in both conditions** — not only
  under the engineered bottleneck, but under heavy demand alone — and
  roughly 250 fewer vehicles even finish their trip within the same
  capped run. That's a stronger and more general result than the gate's
  own "wins under a bottleneck, nothing in free flow" framing expected:
  on this corridor, disabling θ_m doesn't just fail to prevent feeding a
  jam, it appears to destabilize an already structurally-tight junction's
  own phase timing badly enough to violate I5 (max-wait) under ordinary
  heavy demand, bottleneck or not.
  **A trap worth naming plainly**: read delay_s alone and blocking-off
  looks *better* (lower delay) — exactly backwards. A trip that never
  completes contributes zero to that sum, so a run that strands ~250 more
  vehicles necessarily reports a *smaller* total. The trips-completed
  column is what actually orders these four arms correctly; delay_s is
  only meaningful compared within equal completion counts. Added a
  `trips_completed` column to the script's own output table so this
  can't be missed next time either.
  **Why capped at 3600 steps, not run to natural completion**: the first
  full-length run left the blocking-disabled arm rejecting the same
  junction for well over 4000 consecutive ticks with no sign of
  resolving — the recovery fix stops it from being a *permanent* freeze,
  but it doesn't make the underlying heavy-demand-exceeds-this-junction's-
  safe-capacity condition resolve any faster. Capping is itself part of
  the honest result, not a shortcut around it: "still rejecting after
  3600 ticks" is already the finding.
- What this does **not** yet show: the gate's own bottleneck-specific
  claim in isolation, cleanly separated from the heavier "blocking-off
  alone destabilizes this junction" effect — a lighter demand level with
  the same bottleneck (to see whether the free-flow arms stay clean while
  only the bottleneck arm degrades) would isolate that if it's still
  worth doing once the real saturation-flow numbers below exist.

### M4 gate comparison — CA-MP vs. tuned Webster, 3 demand levels, 10 seeds each

`scripts/m4_gate_comparison.py` — same paired-seed design as the M3 gate
(`scripts/bench.py`): both controllers see the identical 10-seed set per
demand level, so seed-to-seed demand noise cancels out of the comparison
rather than adding to it. Webster is re-tuned per demand level from that
level's own measured flows (a fair, non-strawman baseline, not one fixed
timing reused everywhere). CA-MP runs with `enable_blocking=True` — the
real controller, not the ablation's disabled arm. 60 real SUMO runs total
(2 controllers × 3 levels × 10 seeds); raw per-seed results are in
`scripts/m4_gate_results.json`, not just the aggregate.

**Results** (person-delay, mean ± 95% CI over 10 seeds; every run
completed 100% of its trips at every level, so this is a clean comparison
with no completion-rate confound this time):

| demand | webster delay (p-s) | camp delay (p-s) | verdict |
|--------|---------------------|-------------------|---------|
| light  | 69,541 ± 1,837      | 160,326 ± 9,144   | CA-MP loses, ~2.3× worse |
| medium | 183,547 ± 12,349    | 373,888 ± 14,189  | CA-MP loses, ~2.0× worse |
| heavy  | 1,368,840 ± 43,105  | 1,361,664 ± 76,088| statistical tie — CIs overlap almost entirely |

Interlock violations: **zero, in all 60 runs, at every demand level.**
The safety half of the gate — "does not starve any approach" — is fully
met: I5 (`max_wait_not_exceeded`) never fired once across the whole
comparison.

**The honest verdict: M4's gate, taken literally — "CA-MP beats the
tuned fixed-time baseline on person-delay at 3 demand levels" — is not
met.** CA-MP loses decisively at light and medium demand (well outside
each other's CI, not noise) and only ties at heavy demand (a "win" by
raw mean, but the CIs overlap almost completely — reporting that as a win
without the CI would be exactly the kind of unqualified claim this
project has been trying not to make). This is a real negative result,
not a bug: build guide line ~1028 explicitly anticipates this outcome
("CA-MP does not beat MP on cross-street delay... then that is the
result. Report it, analyse why... A negative result honestly analysed
marks better than a fudged positive one") — for a different baseline
(pure MP) but the same principle applies here.

**Why, as best this can be analysed without more instrumentation:** the
`stops_per_vehicle` column (also in the raw results) shows an interesting
crossover — CA-MP has *more* stops than Webster at light/medium (2.1 vs
1.9, 3.1 vs 2.9) but *fewer* at heavy (7.5 vs 8.7). Re-reading §3.7's own
`DECIDE` pseudocode against `camp.py`'s implementation line-by-line
confirms the extend/advance logic matches the spec exactly — this isn't
an implementation bug. The likely mechanism: at light/medium demand,
queues are small and 𝒫(p) differences between phases are close to noise,
so the extend test (`𝒫(current) ≥ max 𝒫 − hysteresis`) rarely fails
decisively, and CA-MP tends to ride each phase out toward its own
`max_green_s` rather than cycling as briskly as Webster's short, already-
well-tuned fixed cycle — more, longer-held phases per unit time than a
demand-blind cycle needs when demand is genuinely light. At heavy demand
the picture partly flips: CA-MP's *lower* stop count despite tied delay
is consistent with `θ_m` gating doing what it's designed to do — declining
to discharge into an already-congested downstream link means fewer, longer
holds instead of many short stop-and-go releases into a jam. That matches
this project's own earlier ablation finding (θ_m's real value shows up
under contention/spillback risk, not as a free-flow average-delay win).

**What this means going forward:** CA-MP Layer 1, as currently scoped
(pressure function minus Terms 4-5, cyclic ring, degradation ladder — no
corridor anticipation/debt yet, and still on the placeholder saturation
flow, not measured per-approach `s_lm`), is exactly as safe as Webster
and has an already-demonstrated, large, real robustness advantage under
heavy demand + an engineered bottleneck (the earlier ablation) — but does
not currently beat Webster's plain average person-delay at light or
medium demand, and only ties at heavy. Reported here rather than tuned
until it looked better, per this project's standing honesty norm.
Concrete, not-yet-tried next steps if this gets revisited: (1) real
saturation-flow calibration — the current uniform placeholder likely
washes out real per-approach capacity differences that would otherwise
let 𝒫(p) differentiate more decisively at light/medium demand; (2) the
`hysteresis_frac`/`k` ring-lookahead constants are §3.9 tunables, never
swept — worth trying smaller hysteresis or an explicit low-demand
"gap-out" rule (not in the given §3.7 pseudocode, but standard real-world
actuated practice) to reduce needless max-green riding; (3) Terms 4-5
(corridor anticipation/debt) are explicitly out of M4's scope per this
milestone's own module docstring, so this comparison is Layer-1-only CA-MP,
not the full algorithm — M7 may change this picture.

### Hysteresis sweep — tried, and it isn't the lever

`scripts/m4_hysteresis_sweep.py` tested `hysteresis_frac` ∈ {0.0, 0.05
(the §3.9 default), 0.15} at light and medium demand, 5 seeds each
(triage scale, not the gate's 10) — the hypothesis above being that a
wide tolerance band was letting CA-MP coast to `max_green_s` instead of
switching promptly.

**Result: every seed produced bit-identical person-delay across all three
`hysteresis_frac` values** — e.g. light demand seed 1 is 170,161.7 person-s
at h=0.0, h=0.05, *and* h=0.15, and the same holds for all 10 seed×level
combinations tested. That's not "hysteresis doesn't matter much" — it's
"hysteresis had zero effect at all," which only happens if the extend
test's tolerance term was never the deciding factor in the first place.

Re-reading the extend condition explains why: `pressures[current] >=
best_pressure - hysteresis_frac * abs(best_pressure)`. If `current`'s
pressure is *already* the outright highest among all candidates —
tolerance band or no tolerance band — then subtracting any hysteresis
amount (0 up to 15% of the max) from the right-hand side changes nothing,
because the comparison was never close enough to need the slack. That is
apparently what's happening here: at light/medium demand, the currently-
green phase's own pressure stays on top of the ranking for the entire
stretch up to `max_green_s`, on its own merits, not by a tie-break
technicality. So the original hypothesis (§3.9's tolerance band is too
generous) was wrong — the tolerance band was never in play. This is a
real, useful negative result in its own right: it rules out the cheapest
possible fix and narrows down where the actual cause has to live — inside
`pressure()`'s own terms (most likely `P_flow`'s `q_l`, which keeps
counting the served phase's own queue while it's green, or `S(p)`'s
switching cost outweighing everything else at low pressure magnitudes),
not in the extend/hysteresis comparison layer built on top of them.

### Root cause confirmed — `S(p)`'s switching cost dominates flow pressure at every demand level tested

`scripts/m4_camp_diagnostics.py` instruments every junction's `camp.propose`
call (without modifying `camp.py`) to classify each tick's decision and log
the actual pressure magnitudes in play, one seed per demand level. This
directly tests the hypothesis the hysteresis result pointed at: that the
switching-cost term `S(p) = λ_s · (yellow_s + all_red_s + startup_lost_s) /
t_dec_s` — a fixed ~9.86-point subtraction for switching away from the
current phase, with this build's defaults — is large enough relative to
typical flow pressure that the currently-green phase never stops being the
outright pressure-maximum, so nothing except hitting `max_green_s` ever
ends a green.

**Confirmed, decisively, at all three demand levels:**

| demand | phase changes | % by max_green timeout | current phase was outright pressure-max | mean flow pressure | switch cost |
|---|---|---|---|---|---|
| light  | 161 | **100%** | **100%** (n=13,120 ticks) | 0.16 | 9.86 |
| medium | 168 | **100%** | **100%** (n=13,744 ticks) | 0.45 | 9.86 |
| heavy  | 217 | **100%** | **100%** (n=17,776 ticks) | 1.98 | 9.86 |

Every single phase change, at every demand level, was a `max_green_s`
timeout — zero were a genuine pressure-driven early exit. The current
phase's pressure was the literal outright maximum on 100% of over 44,000
extend-eligible ticks combined. This means the hysteresis tolerance band
was never once in a position to matter (fully explaining the earlier
sweep's bit-identical result — it wasn't a fluke or an implementation
bug, it's a direct consequence of this), *and* that CA-MP as currently
tuned is functionally a fixed-time controller running every phase to its
own `max_green_s` ceiling — the pressure function has not driven a single
real decision in any test run so far, at any demand level.

**The mechanism, and one important correction to the obvious story:** the
switch cost (9.86, fixed) is 61× typical flow pressure at light demand,
22× at medium, and still ~5× at heavy — shrinking as demand rises (flow
pressure scales with real queue size, the switch cost doesn't), but never
once crossing over into flow pressure actually winning, even at heavy
demand, in this corridor with this build's parameters. So heavy demand's
earlier tie against Webster is *not* CA-MP "becoming adaptive" — it's
still 100% timeout-driven there too. Checking Webster's own computed cycle
lengths directly confirms the real explanation: at light demand Webster's
cycle is a flat 40s floor at every junction, while CA-MP is stuck running
close to its own (much longer) max-green-sum cycle regardless of demand —
at heavy demand, several junctions' *Webster* cycle balloons to 180s,
converging toward CA-MP's already-long fixed cycle. The gap closes because
the baseline's optimal cycle grows to meet CA-MP's stuck-at-maximum
behaviour, not because CA-MP started making real decisions.

**Practical root cause:** `_switch`'s numerator (`yellow_s + all_red_s +
startup_lost_s`, real seconds) and `_flow_pressure`'s output
(`sat_flow_pcu_s × queue_pcu`, small in this build because the placeholder
`sat_flow_pcu_s = 0.5` keeps it low unless queue sizes are large) live on
completely different numeric scales, and the pressure function subtracts
them directly with no normalization between the two. That's a real scale-
mismatch in this build's own parameterization of §3.4 Term 6, not
something the spec's algebra itself forces — a term meant to be a modest
tie-breaking discount ends up as an near-insurmountable flat penalty at
this corridor's actual queue magnitudes.

**One more consequence, worth stating plainly:** because every phase
change observed so far has been a timeout, the fairness term (`F(p)`) and
the I5 max-wait interlock have not been meaningfully exercised in any M4
result reported so far — the "zero starvation, zero violations" safety
result is real, but it's currently being delivered by the max_green
ceiling acting as a de facto fixed-cycle, not by the adaptive fairness
logic actually working. Once the switching-cost scaling is fixed and
pressure starts making real decisions, the fairness/I5 checks will be
exercised for the first time and should be re-verified rather than assumed
to still hold.

### Switching-cost fix — `S(p)` rescaled to match `P_flow`'s own units

`camp._switch` originally returned a bare `λ_s · lost_time_s / t_dec_s` —
real seconds, with no `sat_flow_pcu_s` weighting at all — while every other
term in `pressure()` (`_flow_pressure`, `_block_pressure`, `_fairness`) is a
`sat_flow_pcu_s`-weighted quantity. That's the actual mechanism behind the
root cause confirmed above: `S(p)` was the one term in 𝒫(p) living on a
different numeric scale from the rest, not something tunable-sweeping
(`hysteresis_frac`, `t_dec_s` alone) could fix, because the mismatch itself
grows and shrinks with `sat_flow_pcu_s` — the same quantity every other
term already scales by.

**The fix:** price the lost green time the way `_flow_pressure` prices a
real queue. `mean(sat_flow_pcu_s[m] for m in phase's movements) *
(lost_time_s / t_dec_s)` is a phantom "queue" of the vehicles the candidate
phase could have discharged during the lost clearance time; weighting that
phantom queue by the same mean saturation flow again — exactly how
`_flow_pressure` turns a real `queue_pcu[m]` into a pressure term — brings
`S(p)` onto `P_flow`'s own scale instead of a bare seconds count. This is a
deviation from the guide's literal `λ_s · lost_time_s / t_dec_s` shape (no
`sat_flow_pcu_s` factor there) — flagged in `_switch`'s own docstring
exactly as Term 2's ambiguity is flagged in the module docstring, not
silently changed.

**A real regression caught before it shipped:** the first version of this
fix *summed* `sat_flow_pcu_s` over the candidate phase's green movements
(matching `_flow_pressure`'s own literal shape). Re-running
`m4_camp_diagnostics.py` against the real corridor immediately surfaced why
that was wrong — with one uniform corridor-wide `sat_flow_pcu_s`, summing
makes `S(p)` scale with how many movements a phase happens to bundle, so
multi-movement phases got penalized more to switch into than single-
movement ones, for no reason connected to real switching cost (the
yellow/all-red/startup clearance interval doesn't get longer because more
movements share the next phase). That skew showed up as new
`failsafe_interlock_rejected` events (2-3 per run, all three demand levels)
that the unfixed build never produced. The safety architecture caught every
one — zero unsafe plans ever reached the simulated cabinet, all-red
commanded instead, exactly as `arbiter.tick` is supposed to — but a "fix"
that makes the safety net fire *more often* than the original bug is a real
regression, not an acceptable trade. Switched to the *mean* over the
phase's movements instead of the sum: keeps `S(p)` on the correct
sat_flow-weighted scale without making it depend on movement count.
Re-running the diagnostics after that correction: **zero interlock
violations at all three demand levels, matching the original (buggy)
build's safety record exactly** — the fix is scale-correcting only, not
behavior-distorting.

**Verified, real SUMO runs, before → after:**

| demand | switch cost | switch cost ÷ flow pressure (before) | switch cost ÷ flow pressure (after) | interlock violations |
|---|---|---|---|---|
| light  | 9.86 → 2.46 | 6155% | **1539%** | 0 → 0 |
| medium | 9.86 → 2.46 | 2172% | **543%**  | 0 → 0 |
| heavy  | 9.86 → 2.46 | 498%  | **125%**  | 0 → 0 |

Also re-ran `smoke_m4_camp_runner.py` (full 7-junction real corridor, medium
demand): PASS, zero interlock violations, zero fault events, over 2402
steps — unchanged from M4's original result.

**Honestly, this alone does not unlock pressure-driven decisions yet.**
Phase-change counts at all three demand levels are numerically identical to
the pre-fix run (161 / 168 / 217, still 100% `max_green_s` timeouts) — the
scale mismatch shrank by exactly 4× at every level (since both `P_flow` and
`S(p)` are anchored to the same uniform placeholder `sat_flow_pcu_s = 0.5`
corridor-wide, the ratio between them is invariant to that placeholder's
actual value), but heavy demand's 125% means the switch cost still edges
out flow pressure even there, so the currently-green phase still holds the
outright pressure-max on every tick observed. This is not a sign the fix
failed — it's the same, already-identified deeper limitation the bullet
below described before this fix, now closer to resolved rather than fully
resolved: `P_flow` and `S(p)` both still lean on one conventional
placeholder saturation flow rather than this corridor's real per-approach
capacity, so neither term is at its real scale yet. Deliberately not
"fixed" further by hand-picking a smaller constant to force phase changes
to look pressure-driven — that would be exactly the "tuned until it looked
better" move this project's own honesty norm rules out. The real unlock is
the next bullet.

### Real saturation-flow calibration — built, and it surfaced a real, pre-existing gap

`scripts/measure_saturation_flow.py` measures real per-lane discharge
capacity directly on the corridor network: isolate one movement (every
other kept red, no other traffic present -- saturation flow is *unimpeded*
capacity by definition), queue a heavy backlog using this corridor's own
vType mix (`assign_vtypes.py`'s exact 35/40/20/5 motorcycle/car/auto/bus
split, imported rather than re-declared), hold it green, and time real
discharge crossings past the first `_DISCARD_N` (the startup-lost-time
wave). A real routing ambiguity turned up during its own pilot run and is
worth recording: several movements at this junction's own geometry share
one physical lane feeding two SUMO `linkIndex`es that differ only by
destination *lane*, not destination edge -- an edge-level route can't
disambiguate which one to use, and the first pilot silently measured the
wrong (still-red) link as a result. Fixed by recognizing saturation flow is
a property of the *lane*, not the abstract movement label: `_group_links_
by_lane` measures once per distinct physical lane and applies that result
to every `L{i}` sharing it -- both more correct and side-steps the
ambiguity entirely. 68 of 73 movements corridor-wide got a clean measured
value (5 skipped, insufficient queue depth in their window -- omitted, not
guessed); `extract_tier0_config.py` now loads `sat_flow_calibration.json`
when present and falls back to the original placeholder per-movement for
anything missing.

**This is where re-running `m4_camp_diagnostics.py` with real calibration
wired in stopped being a clean win and became a real finding.** Medium
demand and the full-corridor `smoke_m4_camp_runner.py` (medium demand)
stayed clean -- zero interlock violations, matching every prior result.
**Light demand did not**: the run grew from 2295 to 10887 steps and produced
10235 interlock violations, versus zero in every run before it (uncalibrated,
switch-fix-only, and this same calibration under medium/heavy demand).
Traced with a per-tick instrumented rerun (kept only as this write-up, not
committed as a script) to one junction
(`cluster_1880441740_4393296791`) stuck from step 652 onward: movements
`L6`/`L7` (phase P1) hit their `max_wait_s` bound (452s) with a real,
substantial queue (5.4 PCU) and stayed there, because **`P1`'s pressure was
structurally incapable of ever winning**, not just unlucky. With
`receiving_occupancy` empty (light demand -- nothing downstream is
congested), `P_flow` and `P_block` cancel exactly (the zero-occupancy
property the module docstring already documents), leaving pressure decided
by fairness minus switching cost alone. Fairness's own ceiling is capped at
`λ_f · Σ sat_flow_pcu_s[m]` for the starved movements (`0.6 × (0.4135 +
0.4135) ≈ 0.50` here) -- but `S(p)`'s own fix computes switching cost from
the *same* `sat_flow_pcu_s` values, and for a 3-movement phase that
consistently comes out several times larger than fairness's ceiling
(`1.91` here) at this corridor's real saturation-flow scale. No matter how
long `L6`/`L7` wait -- `wait_ratio` is already capped at `1.0` -- `P1`'s
pressure cannot cross zero while flow/block keep cancelling. That's a
structural deadlock, provable from the numbers, not a near-miss the
hysteresis band or a longer run would have eventually broken.

The safety architecture caught every one of the 10235 rejections -- zero
unsafe plans reached the simulated cabinet, exactly as designed. What it
exposed instead is a second, compounding gap: `_recover_from_fault`
(`runner.py`) unconditionally resets a faulted junction to `ring_order[0]`,
with no notion of *which* movement actually needs serving -- so once `P1`
starts losing this way, recovery keeps landing back on a phase that still
doesn't serve it, `L6`/`L7`'s wait keeps climbing, and the same rejection
repeats every tick for the rest of the run rather than ever resolving.
That gap was already flagged, in the exact words its own docstring uses,
as "not maximally rigorous" -- this is the first time it's actually been
exercised, not a new discovery about the code, but the first real evidence
of the failure mode it warned about.

**Why this took a real calibration run to surface, not the switch-cost fix
by itself:** PROGRESS.md said as much when the fix landed --
*"the fairness/I5 checks will be exercised for the first time and should
be re-verified rather than assumed to still hold."* With the uniform
placeholder, `S(p)` was ~9.86 (pre-fix) or ~2.46 (post-fix, still uniform)
against a fairness ceiling in the same ballpark either way for a uniform-
sat_flow phase -- and every run before this one was still 100%
`max_green_s`-timeout-driven at every demand level, meaning no movement's
wait had ever actually reached its bound in any prior test. Real,
non-uniform per-lane calibration was the first change that let a run last
long enough, and diverge enough phase-to-phase, for a starved movement to
genuinely hit its wait ceiling for the first time in this project's
testing -- so this bug is not new and not caused by miscalibrated data; it
was always reachable, and simply hadn't been reached yet.

### Both gaps fixed, and re-verified against the exact run that failed

Both directions flagged above were built, not just one -- belt and
suspenders, since they fix different halves of the same failure (CA-MP's
own math never reaching the starved movement, and the safety-net recovery
path not knowing where to go if it doesn't):

- **`camp.py`: a starvation override.** New `_critical_phases(cfg, ctx,
  live_phases)` returns every live phase serving a movement within
  `_SKIP_WAIT_MARGIN_S` (the same 15s margin `_skippable` already uses) of
  its `max_wait_s` bound, with real demand -- most-urgent-first. `propose()`
  checks this immediately after the unconditional min-green floor (I3) and
  before the ordinary pressure-based extend decision, not only inside the
  advance branch: pressure can otherwise judge even a totally idle current
  phase the outright best candidate and "extend" it forever, in which case
  the advance branch is never reached at all -- exactly what happened at
  `cluster_1880441740_4393296791`. When a critical phase exists and current
  isn't it, `propose` skips the k-step ring lookahead and the pressure
  ranking entirely for that one decision and advances straight to the most
  urgent one. Can never fire before `min_green_s` (I3 still absolute) --
  verified by a dedicated test, not just asserted.
- **`runner.py`/`arbiter.py`: fault-aware recovery.** `Decision` gained a
  `violated_movements: frozenset[str]` field (Python-side routing data, not
  part of the wire event contract -- `_faulted_event`'s dict stays exactly
  as schema-shaped as before), populated from the union of every rejected
  `Violation.movements` when `mode == "failsafe_interlock_rejected"`.
  `_recover_from_fault` now resumes into whichever ring phase actually
  serves one of those movements, falling back to `ring_order[0]` only when
  none do (every other fault mode, or a violation naming no movement) --
  otherwise a rejection could keep landing recovery back on a phase that
  still doesn't serve the flagged movement, repeating the same rejection
  forever, which is exactly the mechanism that turned one I5 trip into
  10235 of them.

**Tests added, not just the fix:** `_critical_phases` unit tests (empty
when nothing's close, ignores a movement with no real demand, orders
most-urgent-first); a deterministic reproduction of the exact
`cluster_1880441740_4393296791` numbers (idle current phase at pressure
0.0 vs. a 3-movement candidate whose own real sat_flow makes its pressure
provably negative even at `wait_ratio == 1.0`) confirming the override
fires; a test confirming the override never cuts a phase short of
`min_green_s`; a new Hypothesis property test
(`test_camp_never_lets_i5_fire_across_heterogeneous_saturation_flows`,
200 examples) that -- unlike the original safety property test, which
uses a uniform `sat_flow=1.0` and can't exercise this bug class at all --
draws per-phase saturation flow independently and holds `max_wait_s` tight
enough to actually be reachable, asserting `interlocks.check` never fires
over many ticks; and `_recover_from_fault`/`arbiter.tick` tests confirming
`violated_movements` is populated correctly and recovery actually routes
to the phase that serves it (with a fallback test for when it can't).
132 tests pass corridor-wide (was 121 before this fix).

**Re-verified against the exact run that failed, not just the unit
tests:** `m4_camp_diagnostics.py`, full real corridor, all three demand
levels, real calibration data:

| demand | before this fix | after this fix |
|---|---|---|
| light  | steps=10887, **10235 interlock violations** | steps=2387, **0 violations** (3 starvation-override advances fired) |
| medium | steps=2539, 0 violations | steps=2539, 0 violations |
| heavy  | steps=3652 (untested to completion before the fix) | steps=3652, **0 violations** (1 starvation-override advance fired) |

`smoke_m4_camp_runner.py` (full 7-junction corridor, medium demand): PASS,
zero interlock violations, zero fault events, over 2539 steps. The
override firing a small, nonzero number of times (3 at light demand, 1 at
heavy) rather than zero is itself part of the evidence this is doing real
work, not dead code the tests merely tolerate.

**Not yet built:**

- Re-running the hysteresis sweep and the full gate comparison (Webster vs.
  CA-MP) with all of the above in place -- now a meaningful benchmark to
  run, since pressure can no longer structurally strand a movement while
  it's running. Not yet done this session.
- A cleaner isolation of the earlier ablation's bottleneck-specific effect
  from the more general blocking-off-under-heavy-demand effect -- worth
  doing, not required to already have a real, reportable finding.

## M5 — A-CA-MP (Adaptive CA-MP): fixing the pressure function, and giving the controller a memory

Motivating observation, and it was the right one: *the controller does
not learn from past experience.* Investigating that turned up four
distinct places where CA-MP has no memory, at four different timescales,
and — while designing the fix for the shortest of them — one structural
defect in `𝒫(p)` that turns out to explain M4's whole negative gate
result.

`camp.py` is deliberately **not modified**. M4's gate is a recorded
experimental result and a strategy edited after the fact makes it
unreproducible. M5 is a second strategy (`control/strategies/acamp.py`)
that the gate runs *against* CA-MP.

### The defect: M4's flow/block pair can never be positive

`camp.py` computes `P_flow = s_m·q_m` and `P_block = s_m·q_m·θ_m` with
`θ_m = min(θ_max, 1/max(ε, 1−ρ_m))`, and subtracts the second from the
first. But `1/(1−ρ) ≥ 1` for every `ρ ∈ [0,1)`, so **`θ_m ≥ 1` always**,
so the pair is `s_m·q_m·(1−θ_m) ≤ 0` **for every legal input** — and
grows *more negative* as the queue grows. The two terms that constitute
the max-pressure core of a max-pressure controller are jointly a penalty
on having a queue at all. A phase with 20 PCU waiting scores strictly
worse than an identical phase with 0 PCU waiting.

This is not a new observation so much as a re-reading of one already in
`camp.py`'s own docstring, which records the `ρ = 0` special case
("`P_flow` and `P_block` cancel *exactly* ... raw queue size alone cannot
break a tie between two candidate phases") and reasons about it as a
faithful consequence of following §4's reference code over §3.4's prose.
It is faithful to that code. It is also, at every `ρ > 0`, strictly worse
than cancellation. Two Hypothesis property tests now assert both facts
over the whole legal input domain
(`test_m4_flow_minus_block_is_never_positive`,
`test_m4_pressure_decreases_as_queue_grows`) — 500 examples, both pass,
which is to say the defect is confirmed rather than argued.

It is sufficient on its own to explain M4's gate: CA-MP lost worst at
light and medium demand, which is exactly where receiving links are empty
and nothing else in `𝒫(p)` scales with queue size either.

The root cause is the ambiguity M4 flagged and resolved the wrong way.
§3.4's prose defines `P_block` over the queue on the *receiving* link;
§4's reference code reuses `m`'s own upstream `q_pcu`; M4 followed the
code because no lane→downstream-lane queue source existed. One did exist
— `link_lanes.link_to_receiving_lane_map()`, already used for
`receiving_occupancy`. `JunctionContext.receiving_queue_pcu` now carries
the real downstream queue, and the prose reading is available:

    P_press(p) = Σ_m s_m · (q̂_m · gate(ρ_m) − r_m)
    gate(ρ)   = max(0, 1 − (ρ/ρ_jam)^β) ∈ [0, 1]

At free flow this reduces to `Σ s_m·q̂_m` — textbook max-pressure
[Varaiya, TR-C 36 (2013)] — monotone increasing in queue size, the
property M4's version inverted. `gate ∈ [0,1]` replaces `θ ∈ [1,θ_max]`:
a multiplicative discount can reduce a discharge benefit to nothing but
cannot invert its sign, which is precisely the failure `θ` had. The `−r_m`
term supplies the genuine negative pressure "do not discharge into a jam"
needs, from a real measurement rather than a scaled copy of the upstream
queue.

### The four missing memories

1. **Tick-to-tick — architecturally impossible.** `runner.py` rebuilds
   `JunctionContext` from scratch every tick and types a strategy as
   `Callable[[Tier0Config, JunctionContext], SignalPlan]`. A plain
   function has no channel to remember anything, so M4 could not have had
   a memory even if `q_hist` had existed. Fixed by making the strategy a
   callable *object* — same type, owns state. `runner.py` needed no
   signature change.
2. **Seconds — blind to platoons.** M4 set `q̂_l = q_l`, deferring
   arrival augmentation to Layer 2's projected-outflow exchange. But the
   part of `∫ â_l dτ` contributed by vehicles already on this junction's
   own approach needs no exchange — only a look at the lane.
   `JunctionContext.approaching_pcu` supplies it via a time-to-arrival
   test (deliberately a *time* test, not Advanced-MP's fixed distance;
   this corridor's vType mix means a bus at 2 m/s and a motorcycle at
   14 m/s are not interchangeable at equal distance).
3. **Hours/days — no demand profile.** `control/memory.py` builds the
   `q_hist` §3.8 named, as a per-(junction, movement, 15-min bin) EWMA
   across runs, persisted to JSON. One SUMO seed is treated as one *day*:
   same time-of-day demand shape, different stochastic realization.
4. **Across runs — hand-set constants.** `control/tuning.py` fits
   `AcampConfig` with CMA-ES. PROGRESS.md's own M4 history — a hysteresis
   sweep that came back bit-identical, a diagnostic run to find `S(p)`'s
   scale, a rescale, a starvation deadlock, an override — is a record of
   doing this by hand, one hypothesis at a time. That is a numerical
   optimization problem.

### Removed rather than fixed: the subtracted switching cost

There is no switching term in `𝒫(p)` at all. M4's `S(p)` is a per-phase
constant, and a constant is `O(1)` against pressure differences that
scale with queue size, so some demand level below which it dominates
always exists — measured at 61x/22x/5x typical flow pressure, with 100%
of phase changes being `max_green_s` timeouts. The rescale that followed
was correct as far as it went and then produced a structural starvation
deadlock needing an override to contain. Both failures are the same
shape: a scale-free comparison decided by a term that does not scale.

Switching is now a separate test between incumbent and challenger,
`switch iff max_p 𝒫(p) > 𝒫(current) + F(scale)`, with `F(x) = κ·x^α` and
`α` constrained **strictly inside (0,1)** — the sublinearity condition
throughput-optimality needs when a switching penalty is introduced at all
[Xu et al., TR-C 137 (2022), Thm. 3]. `F(x)/x → 0` makes M4's failure
mode unreachable *by construction* rather than by tuning: however large
`κ` is, the hold bias eventually stops mattering. `α = 0` is exactly M4's
constant and `sublinear_hold_bias` raises rather than clamps on it — a
silent reconstruction of a known bug is worse than a crash.

`hysteresis_frac` is gone. M4's own sweep found it bit-identical across
{0.0, 0.05, 0.15}; `F(scale)` is that tolerance band, made
state-dependent and given a reason to exist.

### Gate — 4 arms x 3 demand levels x 10 seeds, paired

`scripts/m5_gate_comparison.py`, same paired-seed methodology as M3's and
M4's gates. M4's controller runs as a **live arm** rather than being
quoted, so differences are attributable to the controller and not to a
changed harness or the calibration that landed between milestones.
Evaluated on seeds 1..10 — the same seeds M4's gate used, and disjoint
from the 101..110 the parameters and profile were fitted on.

Harness validation: Webster reproduces M4's recorded numbers to the digit
(69,542 / 183,547 / 1,368,840 vs. 69,541 / 183,547 / 1,368,840).

| level | arm | person-delay (mean ± 95% CI) | viol | vs Webster |
|---|---|---|---|---|
| light | webster | 69,542 ± 1,837 | 0 | — |
| light | camp (M4) | 188,822 ± 9,209 | 0 | +171.5% |
| light | **acamp** | 59,511 ± 3,109 | 0 | −14.4% |
| light | **acamp tuned** | **56,295 ± 5,957** | 0 | **−19.0%** |
| medium | webster | 183,547 ± 12,349 | 0 | — |
| medium | camp (M4) | 434,729 ± 16,004 | 0 | +136.8% |
| medium | acamp | 224,883 ± 27,404 | 0 | +22.5% |
| medium | **acamp tuned** | **198,890 ± 16,349** | 0 | **+8.4% (CIs overlap — tie)** |
| heavy | webster | 1,368,840 ± 43,105 | 0 | — |
| heavy | camp (M4) | 1,523,050 ± 66,583 | 0 | +11.3% |
| heavy | acamp | 1,508,017 ± 59,171 | 2 | +10.2% |
| heavy | acamp tuned | 1,603,074 ± 79,624 | 8 | +17.1% |

**Light demand: the M4 gate's stated goal is met** — A-CA-MP beats the
tuned fixed-time baseline on person-delay, CIs disjoint, zero interlock
violations. **Medium: a statistical tie** after tuning (the CIs overlap:
182,541 vs 195,896), up from a decisive loss. **Heavy: still a loss, and
tuning made it worse.**

The decision accounting is the clearest evidence the diagnosis was right.
M4 measured 100% of phase changes as `max_green_s` timeouts and 0%
pressure-driven, across 44,000+ ticks. A-CA-MP tuned, one light-demand
run: 363 pressure-driven switches against 36 timeouts — **91%
pressure-driven**. The pressure function is making real decisions for the
first time in this project.

### Answering M4's own open question: re-running its gate with the fixes in

M4 left this explicitly not-yet-done. The `camp` arm above **is** that
re-run — post-switching-cost-fix, post-calibration, post-starvation-
override. Result: 188,822 / 434,729 / 1,523,050 against M4's originally
recorded 160,326 / 373,888 / 1,361,664. **The fixes made CA-MP measurably
worse at all three demand levels.** They were each correct in isolation
and each addressed a real diagnosed problem; they did not address the
sign defect underneath, and the starvation override they added is
expensive precisely because `𝒫(p)` kept ranking starved phases last.

### Tuning — what CMA-ES found, and where it failed

36 candidates x 2 levels x 2 seeds, `max_steps=1500`, training seeds
only. Best objective 48,673 against a first candidate of 85,125.

| param | default | tuned | reading |
|---|---|---|---|
| `eta_arrival` | 0.5 | 1.02 | anticipation weighted ~2x higher — a strong endorsement of the arrival term |
| `rho_jam` | 0.75 | 0.91 | gate should stay open longer than assumed |
| `beta_gate` | 2.0 | 3.71 | sharper knee — flat, then sudden, as capacity really behaves |
| `lambda_f` | 0.6 | 0.59 | §3.9's fairness default was already right |
| `gamma` | 3.0 | 3.57 | ~unchanged |
| `kappa_switch` | 0.5 | 0.46 | ~unchanged |
| `alpha_switch` | 0.5 | 0.11 | far more sublinear than assumed |
| `k` | 2 | 4 | wants full ring lookahead, not §3.7's 2 |

**And it broke heavy demand.** Trained on light+medium only, the search
had no reason to preserve switching resistance under congestion:
`α = 0.11` makes `x^α` grow so slowly that the hold bias is nearly
constant, so it does not scale up as the junction loads. Heavy demand
regressed from +10.2% to +17.1% and from 2 interlock violations to 8.

This is exactly the failure mode the LESCMP paper describes for vanilla
max-pressure — "PWBP fails because it switches too frequently" — arrived
at from the opposite direction. M4 was frozen by too much switching
resistance; the tuner, optimizing where congestion never appears, removed
almost all of it. The literature's own prescription (switching resistance
should *rise* with congestion, sublinearly) is what both failures violate
in opposite directions, and the sublinearity bound is what stopped the
tuner going all the way to M4's constant.

Two honest readings, and the second is more likely: (a) train on all
three levels; (b) one parameter vector across all demand regimes is the
wrong model, and the parameters should be conditioned on observed
congestion — which is itself a memory idea, and the natural M6.

### The demand memory does not pay for itself yet — a negative result

`scripts/m5_sensor_degradation.py`. The gate runs on SUMO ground truth,
so `confidence` is always 1.0, `select_mode` always returns "camp_full",
and the blending rung never executes (`blended: 0` in every gate run).
Measuring a memory in a regime where it is dormant would be claiming
credit for dead code, so confidence is injected at 0.6 — the
"camp_blended" band — to stand in for M8's vision pipeline degrading.

| level | memory ON | memory OFF (M4's fixed-time fallback) | delta |
|---|---|---|---|
| light | 101,325 ± 8,691 | 73,571 ± 3,354 | **ON is 37.7% worse** |
| medium | 235,590 ± 18,691 | 233,860 ± 27,900 | tie |

Blending is verified live (14,356 blended ticks/run; the OFF arm is
8,604/8,604 ticks of `fallback_fixed_time`, i.e. exactly M4's behaviour).
So the comparison is sharper than it was designed to be: it is not
"memory vs. no memory" but **"blend against history vs. fall back to
fixed-time"** — and fixed-time wins at light demand, decisively.

The likely mechanism: `blend(live, hist, c) = c·live + (1−c)·hist` treats
confidence as a Bayesian precision weight, but a 15-minute cross-run mean
is a *smoothed* quantity — much lower variance and much lower information
content than a noisy live reading. Mixing 40% of it into the live state
washes out exactly the queue differences pressure needs to discriminate
between phases. Historical priors help where live data is *absent*, not
where it is merely *noisy*, and the ladder currently conflates those.
M4's choice to fall back to fixed-time rather than half-implement a blend
is, on this evidence, the better engineering call and is reinstated as
the default recommendation until the blend is reformulated.

### Tests

177 pass corridor-wide, up from 134, zero regressions. 43 new:
- Two property tests establishing the M4 sign defect over its whole legal
  input domain, and their A-CA-MP counterparts establishing monotonicity.
- `test_acamp_never_lets_an_interlock_fire` in the heterogeneous
  saturation-flow form M4's suite adopted after a uniform-`sat_flow`
  test proved unable to catch the starvation bug that shipped — with the
  *switching parameters drawn too*, since a safety proof that only holds
  at the default parameter vector is worthless once the optimizer runs.
- Sublinearity of `F(x)` asserted as the exact analytic decay
  `F(x)/x = κ·x^(α−1)` rather than a threshold.
- `memory.py`: cold start, EWMA tracking a demand shift, a short run not
  diluting a bin it never reached, in-progress runs not contaminating
  their own history, atomic save.
- `tuning.py`: bounds, `alpha_switch` unreachable outside (0,1), the
  safety penalty ranking, and one test that **records a limitation** —
  where violations are binary rather than graded, the penalized region is
  flat and the search can sit in it. The safety guarantee comes from
  `interlocks.check`, which no parameter can reach, never from the
  objective.

### Not yet built

- Re-training across all three demand levels, or (better) conditioning
  parameters on observed congestion.
- Reformulating the blend so history is used where live data is absent
  rather than where it is noisy.
- The heavy-demand interlock rejections all land on
  `cluster_1880441740_4393296791` — the same junction as M4's deadlock.
  Not diagnosed here.
- Terms 4-5 (corridor anticipation / debt) still require the Green
  Corridor Engine and remain M7's.
