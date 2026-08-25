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

**Not yet built:**

- Real saturation-flow calibration (`sat_flow_pcu_s` is currently one
  conventional placeholder value corridor-wide, not measured per
  approach) — still a candidate lever on the light/medium gap, though the
  hysteresis result above means it's no longer the *only* remaining
  suspect.
- A cleaner isolation of the earlier ablation's bottleneck-specific effect
  from the more general blocking-off-under-heavy-demand effect — worth
  doing, not required to already have a real, reportable finding.
- Instrumenting `pressure()`'s individual terms per tick (flow/block/
  fairness/switch, not just the combined value) at light demand, to see
  which term is actually keeping the current phase's pressure on top for
  so long — the hysteresis sweep ruled out the tolerance band itself, but
  not yet identified which of the four remaining terms is the real cause.
