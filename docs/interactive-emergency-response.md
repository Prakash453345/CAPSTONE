# Interactive Traffic Management & Emergency Response

This document describes the interactive, closed-loop layer built on top of the
ITMS platform: an operator opens the Command Center, watches live SUMO traffic,
injects an anomaly that actually affects the simulation, dispatches an emergency
vehicle, and the system computes an anomaly-aware route, coordinates signals into
a green corridor, drives the vehicle through SUMO, and re-routes it continuously
as conditions change — terminating cleanly on arrival with a tamper-evident audit
trail.

It is additive. The automated milestone pipeline (M1 streaming, M2–M5 signal
control, M6 anomaly detection, its incident injector and evaluation gate) is
untouched and still runs. This layer adds a **human-controlled interactive
path** that shares the same domain model, event language, and safety kernel.

- [The closed loop](#the-closed-loop)
- [Architecture](#architecture)
- [The contribution (and what is just a standard algorithm)](#the-contribution)
- [Dynamic emergency routing cost model](#dynamic-emergency-routing-cost-model)
- [Interactive anomaly model](#interactive-anomaly-model)
- [Green corridor](#green-corridor)
- [Continuous monitoring & re-routing](#continuous-monitoring--re-routing)
- [Signal safety: the arbitration ladder](#signal-safety-the-arbitration-ladder)
- [Event contracts](#event-contracts)
- [The three lifecycles](#the-three-lifecycles)
- [Configuration reference](#configuration-reference)
- [How to run](#how-to-run)
- [How to demonstrate](#how-to-demonstrate)
- [Testing](#testing)
- [Deliberately out of scope](#deliberately-out-of-scope)

---

## The closed loop

```
SEE          live SUMO traffic on the corridor map (VehiclePositionUpdated / ApproachState)
UNDERSTAND   operator (or M6 detector) marks an anomaly -> normalised Anomaly, applied to SUMO
DECIDE       RoutePlanner scores candidate routes with the dynamic cost model
ACT          green corridor proposes signal preemptions -> arbiter -> interlocks -> SUMO;
             the emergency vehicle is spawned and driven
MONITOR      per-tick position + condition sampling; EmergencyVehicleUpdated stream
ADAPT        automatic re-route on a blocked/severe anomaly ahead or a materially cheaper path,
             with cooldown + minimum-progress gates so it never oscillates
```

On arrival the corridor is terminated, signals return to normal control, the
`EmergencyRequest` reaches `COMPLETED`, and every transition is recorded in a
hash-chained history.

---

## Architecture

### Services

| Service | Role in this layer |
|---|---|
| **sim-service** | Runs SUMO. `SIM_MODE=live` starts `sim_service.live.run_live`, which is `control.runner.run_controlled_scenario` with its live hooks on: publish the M1 traffic stream, pace to real time, drain `commands.operator` each tick, and consult a rung-3 corridor-preemption proposal source. Owns the routing engine, the operator-anomaly controller, the emergency controller, and the green-corridor controller. |
| **api-service** | `POST /v1/commands` encodes an operator command onto `commands.operator`. `WebSocket /v1/stream` fans out every event topic to the browser. |
| **web-app** | Vite + React + TypeScript operator console. `TrafficDataBridge` owns the active data provider (live WebSocket or in-browser mock) and pumps normalised snapshots into Zustand stores. |

### Two SUMO loops, on purpose

| Loop | Entry point | What it is |
|---|---|---|
| **M1 streaming** | `adapters/sumo/traci_loop.run` | One-way SUMO → Redis at 1 Hz. No controller, no commands. **Unchanged.** |
| **Live command-driven** | `control/runner.run_controlled_scenario` via `sim_service/live/service.py` | The arbitration ladder governs every signal-controlled junction. Promoted to the live service by three additive parameters (`publish_traffic_state`, `on_tick`, `pace_realtime_factor`) plus `preempt_source`. No batch caller passes them, so the offline gates are byte-for-byte unaffected. |

### Command path

```
web-app  postCommand({event_type, payload})
   -> api-service  POST /v1/commands   (encode_envelope -> publish "commands.operator")
   -> sim-service  RedisStreamsSyncConsumer.drain() inside on_tick, once per sim step
   -> _build_dispatch routes by event_type to the anomaly / emergency controller
```

### Event flow

```
sim-service publishes:
  traffic.vehicle-positions   VehiclePositionUpdated     (M1 stream, reused verbatim)
  traffic.updated             ApproachState
  signal.changed / .faulted   SignalChanged / SignalFaulted   (from the arbiter)
  anomaly.updated             AnomalyUpdated
  emergency.request-updated   EmergencyRequestUpdated
  emergency.vehicle-updated   EmergencyVehicleUpdated
  emergency.corridor-updated  GreenCorridorUpdated

api-service subscribes to all of the above and relays each as a JSON envelope on /v1/stream.
```

### Module map (`sim_service/`)

```
routing/
  graph.py       RoadGraph (nodes = SUMO edges) + link_movements (tl,from,to -> {L{i}})
  cost.py        RouteCostModel — the alpha..zeta formula, normalised
  search.py      GraphSearchEngine — weighted Dijkstra + k_shortest via diversity penalty
  planner.py     RoutePlanner — plan() (recommended + alternatives), evaluate() (cost a known path)
live/
  service.py         run_live — wires everything and calls run_controlled_scenario
  anomaly_control.py OperatorAnomalyController — applies/reverts lane-speed effects in SUMO
  emergency_control.py EmergencyController — request state machine, EV spawn/track, monitoring
  green_corridor.py  GreenCorridorPlanner + CorridorController (rung-3 proposal source)
  corridor.py        load_corridor — Tier-0 configs, Webster strategy per junction, lane maps
signal_controller/
  arbiter.py     the arbitration ladder — the ONLY place a signal is commanded
control/safety/
  interlocks.py  I1–I7 as pure predicates over a SignalPlan
```

---

## The contribution

The path search itself is a **standard weighted Dijkstra** (`k_shortest` adds a
diversity penalty on already-used edges to produce genuinely different
alternatives). No new pathfinding algorithm is claimed.

The ITMS-specific contribution is the **decision framework around it**:

1. **Dynamic Emergency Routing Cost Model** — a six-term, individually
   normalised, fully configurable edge cost (`EmergencyRoutingConfig`).
2. **Anomaly Impact Assessment** — LOW / MEDIUM / HIGH / BLOCKED, each mapped to
   a concrete SUMO effect and a routing penalty; only a genuinely BLOCKED road
   is removed from the graph.
3. **Traffic-Aware Routing** — live per-edge occupancy and mean-speed fraction
   from TraCI fold into the cost every time a route is computed.
4. **Signal Coordination & Green Corridor** — time-boxed movement reservations
   proposed to the Signal Controller, never commanded directly.
5. **Continuous Re-evaluation** — trigger + cooldown logic that re-routes a
   moving vehicle without oscillation or per-tick recompute.

Every weight, penalty, threshold, and green-corridor parameter lives in one
frozen dataclass. The planner returns a `RouteResult` carrying the full
`RouteCostBreakdown` and the explanation lists (signalised intersections,
congested segments, anomalous segments avoided, `weights_used`) so the UI can
answer "why this route".

---

## Dynamic emergency routing cost model

`RouteCostModel.edge_cost(edge, conditions)` — for one graph edge:

```
edgeCost =  travel_time_weight  * travel_time_norm
          + congestion_weight   * congestion_norm
          + anomaly_weight      * anomaly_norm
          + signal_delay_weight * signal_delay_norm
          + disruption_weight   * disruption_norm
          + reliability_weight  * reliability_norm
```

| Term | Raw quantity | Normalisation |
|---|---|---|
| **travel_time** | `free_flow_time / speed_frac`, where `speed_frac = mean_speed_frac` (live) or `1 − 0.7·congestion`, clamped to `[0.12, 1]` | ÷ `travel_time_ref_s` (60 s ≈ 1.0) |
| **congestion** | occupancy index `0..1` | already `0..1` |
| **anomaly** | `(severity_penalty − 1) + impact_penalty_scale · estimated_impact` | bounded; BLOCKED ⇒ `inf` |
| **signal_delay** | `signal_delay_s[phase]` for a signalised entry (`green` 2 s … `red` 22 s … `unknown` 12 s) | ÷ 22 |
| **disruption** | edge length in metres | ÷ `disruption_ref_m` (400 m ≈ 1.0) |
| **reliability** | `reliability_variance_weight · min(0.5, congestion_variance)` `+ 0.3` if an anomaly is active | bounded |

- **BLOCKED is not "cost = infinity in the search."** Edges whose live severity
  is BLOCKED are removed from the graph *before* search (`RoadGraph.without_edges`),
  so a blocked source or destination produces a clear typed error
  (`NoRouteError("the emergency vehicle's current road is blocked")`), not a
  silent failure.
- A route is flagged **unreliable** when its summed `reliability_cost` exceeds
  `reliability_reject_threshold` (0.85) — surfaced, not rejected.
- `RoutePlanner.evaluate(edges, conditions)` costs an *already-chosen* path
  without searching — this is what continuous monitoring compares against a
  fresh `plan()`.

See the [configuration reference](#configuration-reference) for every default.

---

## Interactive anomaly model

All anomaly sources normalise to one `itms_domain.anomaly.Anomaly` value object,
distinguished by `source`:

| Source | Origin |
|---|---|
| `OPERATOR` | operator drew it on the map |
| `SUMO_INJECTOR` | the M6 schedule-driven incident injector |
| `GRAPH_MODEL` | the M6 graph-autoencoder detector, on confirmation |
| `VISION` | reserved for M8 (not implemented) |

`AnomalyType`: `ACCIDENT`, `VEHICLE_BREAKDOWN`, `LANE_BLOCKAGE`,
`ROAD_OBSTRUCTION`, `HEAVY_CONGESTION`, `STALLED_VEHICLE`, `UNKNOWN`.

### Severity → SUMO effect (`OperatorAnomalyController`)

An operator anomaly is not a frontend decoration: it changes the simulated
lanes' max speed via TraCI, so downstream traffic actually slows and the router
sees it.

| Severity | Lane speed kept | `estimated_impact` |
|---|---|---|
| `LOW` | 70 % | 0.25 |
| `MEDIUM` | 45 % | 0.50 |
| `HIGH` | 20 % | 0.80 |
| `BLOCKED` | ~0 (0.1 m/s crawl) | 1.00 |

The controller stores each lane's original `getMaxSpeed`, applies the reduction,
and restores it exactly on clear / auto-expire (time-boxed anomalies carry a
`duration_s`). It republishes `AnomalyUpdated` every 10 s while active so late
subscribers converge.

---

## Green corridor

**Goal:** the emergency vehicle meets a green at every signalised junction on its
route — *without the route planner ever commanding a signal*.

### Planning (`GreenCorridorPlanner`, pure)

1. Walk the route's consecutive edge pairs. For each pair `(a, b)` crossing a
   signalised junction, look up the SUMO link indices that turn uses:
   `RoadGraph.movements_for(tl_id, a, b) -> {"L0", "L1", …}`.
2. Predict the vehicle's arrival at each junction from cumulative free-flow time
   along the route.
3. Build a `CorridorReservation` per junction: hold those movements green from
   `arrival − corridor_prepare_lead_s` to `arrival + corridor_release_lag_s`,
   shifted forward if needed to keep `corridor_min_gap_s` between windows.
4. The set of reservations is a `GreenCorridorRequest` (`PROPOSED`).

### Execution (`CorridorController`)

- On `ACTIVATE_CORRIDOR` the corridor is armed (`ACTIVE`) and the vehicle is
  spawned in SUMO (`traci.vehicle.add` + `setRoute`).
- Each tick, `preemption_plan(cfg, ctx)` is handed to the arbiter as its
  **rung-3 proposal source**. When a reservation window is open at that
  junction it returns a `SignalPlan(source="corridor_preemption")`:
  - the EV's phase already live ⇒ a one-tick same-phase **hold**;
  - a different phase live ⇒ a two-step **switch** that finishes the current
    phase's remaining min-green, clears it (`yellow_s` + `all_red_s` from the
    Tier-0 config), then goes to the EV's phase.
- The arbiter runs that plan through the **same `interlocks.check`** as any
  strategy plan. A plan that would truncate min-green, skip a clearance
  interval, blow the per-junction preemption budget, or starve a movement past
  `max_wait_s` is **rejected**, recorded in `Decision.notes`, and the junction
  falls back to its normal strategy — a corridor request never forces all-red.
- As the vehicle physically clears each junction, that reservation is released
  and the junction resumes normal control. When all are cleared the corridor is
  `COMPLETED`.

The domain enforces its own invariants: `GreenCorridorRequest.__post_init__`
requires reservations ordered by route position; `peak_concurrency()` must stay
≤ `corridor_max_simultaneous`.

---

## Continuous monitoring & re-routing

`EmergencyController._monitor_routes` runs every `_MONITOR_INTERVAL_S` (3 s) for
each non-terminal `ROUTE_READY` / `IN_TRANSIT` request.

**Triggers**

| Trigger | Detected by |
|---|---|
| A BLOCKED anomaly on the road ahead | `_blocked_or_severe_ahead` — immediate |
| A new HIGH/BLOCKED anomaly on the road ahead | fires once per anomaly id |
| A materially cheaper path exists | `RoutePlanner.evaluate(remaining).score` > fresh `plan().score` × (1 + `reroute_cost_increase_frac`) |

**Gates (against oscillation and per-tick recompute)**

- `reroute_cooldown_s` (30 s) since the last route was set — manual or automatic.
- `reroute_min_progress_frac` (3 %) of the *current* route driven since it was set.
- The 3 s monitor interval per request.
- The hysteresis band on the cost comparison itself.

**In-flight re-route** replans from the vehicle's current edge (the request's
`source_edge` is unchanged), pushes the new edge list to SUMO
(`traci.vehicle.setRoute`), and re-arms the green corridor from the new route.
A re-route that finds **no** path *holds* the current route and cools down — a
moving vehicle is never abandoned; only the *initial* routing failure cancels a
request.

---

## Signal safety: the arbitration ladder

`signal_controller/arbiter.py::tick` is the single chokepoint. `TraCICabinet.command()`
→ `traci.trafficlight.setRedYellowGreenState()` is the only signal write in the
codebase.

```
1. Hardware / safety faults        -> failsafe (observe, alarm, never fight)
2. Manual operator override        (no requester yet)
3. Corridor preemption             <- the green corridor, as of this work
4. Adaptive optimiser plan         (A-CA-MP)
5. Fixed-time fallback
```

Every plan from rungs 3–5 passes `interlocks.check(plan, ctx, cfg)`:

| Rule | Invariant |
|---|---|
| I1 | no two conflicting protected movements simultaneously green |
| I2 | every conflicting green→green transition gets yellow + all-red ≥ geometry minimum |
| I3 | min-green is never truncated, by any requester including preemption |
| I4 | a started pedestrian phase always completes walk + clearance |
| I5 | no movement waits past `max_wait_s` while it has demand |
| I6 | a fault reaches a defined safe state; never command into a faulted phase |
| I7 | commanded and read-back state converge, or commanding stops (in `arbiter.tick`) |
| `PREEMPT_BUDGET` | `max_preempt_s_per_hour` per junction — only applies to `source == "corridor_preemption"` |
| `RING_INTEGRITY` | the plan's first phase is a configured member of this junction's ring |

---

## Event contracts

All schemas live in `contracts/events/*.avsc`; `packages/common/itms_common/events.py`
is the only place that touches fastavro.

| Schema | Topic | Direction |
|---|---|---|
| `anomaly_create_requested.avsc` | `commands.operator` | operator → sim |
| `anomaly_clear_requested.avsc` | `commands.operator` | operator → sim |
| `anomaly_updated.avsc` | `anomaly.updated` | sim → UI |
| `emergency_request_created.avsc` | `commands.operator` | operator → sim |
| `emergency_command.avsc` | `commands.operator` | operator → sim (`RECALCULATE` / `CANCEL` / `ACTIVATE_CORRIDOR`) |
| `emergency_request_updated.avsc` | `emergency.request-updated` | sim → UI (7-state lifecycle + route + alternatives + cost breakdown) |
| `emergency_vehicle_updated.avsc` | `emergency.vehicle-updated` | sim → UI (live position while driving) |
| `green_corridor_updated.avsc` | `emergency.corridor-updated` | sim → UI (`proposed` / `activated` / `junction_passed` / `terminated`) |

Every event is wrapped in `envelope.avsc` with the payload as nested Avro bytes.

---

## The three lifecycles

### Anomaly

```
(operator draws / detector confirms) --create--> ACTIVE
ACTIVE --clear / auto-expire--> RESOLVED
ACTIVE --cancel--> CANCELLED
```

`Anomaly` is a frozen value object; `resolved(...)` / `cancelled(...)` return a
new instance and record the reason in `metadata`.

### Emergency request (`itms_domain.emergency.EmergencyRequest`)

```
CREATED --start_routing--> ROUTING --route_ready--> ROUTE_READY
ROUTE_READY --activate_corridor--> GREEN_CORRIDOR_ACTIVE --depart--> IN_TRANSIT
ROUTE_READY --dispatch--> IN_TRANSIT
IN_TRANSIT --reroute--> IN_TRANSIT            (a new route mid-transit)
ROUTE_READY --reroute--> ROUTE_READY
* (non-terminal) --arrive--> COMPLETED
* (non-terminal) --cancel--> CANCELLED
ROUTING --route_failed--> CANCELLED           (initial routing only)
```

`apply(action, …)` raises `IllegalRequestTransition` for a disallowed action and
returns a **new** frozen instance. Each transition is a `RequestTransition`
linked into a **tamper-evident hash chain** (`itms_domain.audit.entry_hash`,
`verify_chain()`), so an edit to the attached route or any past transition is
detectable.

### Green corridor (`itms_domain.emergency.GreenCorridorRequest`)

```
PROPOSED --activate--> ACTIVE --(all junctions cleared)--> COMPLETED
ACTIVE --request cancelled / rerouted / superseded--> CANCELLED
```

---

## Configuration reference

`itms_domain.routing.EmergencyRoutingConfig` — one frozen dataclass, passed to
`RoutePlanner`, `RouteCostModel`, `GreenCorridorPlanner`, and
`CorridorController`. `.validate()` returns a list of problems; an invalid
config surfaces as `NoRouteError("routing config is invalid: …")`.

| Field | Default | Meaning |
|---|---|---|
| `travel_time_weight` | 1.0 | α — free-flow-adjusted travel time |
| `congestion_weight` | 0.6 | β — live occupancy |
| `anomaly_weight` | 1.0 | γ — anomaly severity + impact |
| `signal_delay_weight` | 0.4 | δ — expected junction delay |
| `disruption_weight` | 0.5 | ε — route length / hop count |
| `reliability_weight` | 0.3 | ζ — condition instability |
| `severity_penalty` | `{low:1.25, medium:2.0, high:4.0, blocked:inf}` | multiplicative anomaly factor |
| `impact_penalty_scale` | 3.0 | linear term scaled by `estimated_impact` |
| `signal_delay_s` | `{green:2, yellow:6, red:22, unknown:12}` | seconds by shown phase |
| `reliability_variance_weight` | 1.5 | weight on recent congestion variance |
| `reliability_reject_threshold` | 0.85 | above this a route is flagged unreliable |
| `travel_time_ref_s` | 60.0 | normalisation: seconds ≈ 1.0 |
| `disruption_ref_m` | 400.0 | normalisation: metres ≈ 1.0 |
| `max_alternatives` | 2 | extra routes returned beyond the recommended one |
| `reroute_cost_increase_frac` | 0.35 | re-route if remaining cost exceeds a fresh plan by this fraction |
| `reroute_cooldown_s` | 30.0 | minimum time between re-routes |
| `reroute_min_progress_frac` | 0.03 | ignore triggers in the first 3 % of the route |
| `reroute_on_blocked_edge` | true | re-route immediately on a BLOCKED edge ahead |
| `reroute_on_new_severe_anomaly` | true | re-route on a new HIGH/BLOCKED anomaly ahead |
| `corridor_prepare_lead_s` | 15.0 | open a junction this long before predicted arrival |
| `corridor_release_lag_s` | 4.0 | hold it this long after predicted pass |
| `corridor_min_gap_s` | 5.0 | minimum spacing between two junctions' windows |
| `corridor_max_simultaneous` | 3 | hard cap on concurrent preemptions per corridor |

Tier-0 signal parameters (`min_green_s`, `yellow_s`, `all_red_s`, `max_wait_s`,
`max_preempt_s_per_hour`, conflict matrix) are per-junction and extracted from
the SUMO network by `scenarios/networks/vijayawada/extract_tier0_config.py`.

`AnomalyImpactConfig` (`sim_service/live/anomaly_control.py`) holds the severity →
SUMO effect table shown [above](#severity--sumo-effect-operatoranomalycontroller).

---

## How to run

### Prerequisites

- Python 3.11+, the repo's virtualenv (`.venv`), SUMO (`eclipse-sumo` wheel is
  in the venv), a running Redis.
- Node 18+ for the web-app.

### Live simulation service

```bash
# Redis must be reachable at REDIS_URL (default redis://localhost:6379/0)
SIM_MODE=live \
SIM_DEMAND=light \          # light | medium | heavy
SIM_REALTIME_FACTOR=1.0 \   # >1 = faster than real time
python -m sim_service.main
```

`SIM_MODE=sumo` (default) keeps the untouched M1 streaming loop.
`SIM_MAX_STEPS=N` stops after N steps (used by smoke scripts and tests).

### API service

```bash
uvicorn api_gateway.main:app --port 8000
```

`POST /v1/commands` `{ "event_type": "...", "payload": { ... } }` publishes an
operator command. `WebSocket /v1/stream` streams every event as a JSON envelope.

### Web app

```bash
cd web-app
npm install
npm run dev        # http://localhost:5173, proxies /api and /ws to :8000
```

Switch the top-bar **Data** toggle to **Live** to read the WebSocket, or **Sim**
for the self-contained in-browser mock (no backend needed).

---

## How to demonstrate

End-to-end, matching the closed loop:

1. **Start** Redis, then `SIM_MODE=live SIM_DEMAND=light python -m sim_service.main`,
   then `uvicorn api_gateway.main:app --port 8000`, then `npm run dev` in `frontend`.
   Open the Command Center, set Data → **Live**. Vehicles move on the corridor.
2. **Create an anomaly.** "Create anomaly" → click a road → choose
   *Lane Blockage*, severity *High*, a duration → Create. Traffic slows on that
   edge in SUMO within a couple of seconds; the anomaly appears in the feed and
   on the map.
3. **Dispatch.** "Emergency response" → pick a unit → click a source road and a
   destination road → "Calculate route". The route draws on the map with its
   explanation: ETA, distance, intersections, signals, signal delay, anomalies
   avoided, cost breakdown bar, route score, reliability.
4. **Activate the green corridor.** The panel switches to live corridor status:
   a chip per reserved junction (held / cleared), a progress bar, ETA. The
   vehicle is spawned and starts driving; `signal.changed` events with
   `source == "corridor_preemption"` appear as it approaches each junction.
5. **Force a re-route.** Drop a *Blocked* anomaly on a road ahead of the moving
   vehicle. Within ~3 s the request shows "Auto-rerouted: road blocked ahead …",
   the route redraws from the vehicle's current position, and the corridor
   re-arms around the new path.
6. **Arrival.** The vehicle reaches its destination, the corridor terminates,
   signals return to normal, the request reaches **Completed**, and the History
   panel shows the full transition chain.

### Scripted smokes (need Redis + SUMO)

```bash
python scripts/smoke_live_anomaly.py   light     # operator anomaly path
python scripts/smoke_live_corridor.py  light     # emergency + green-corridor path
```

Each publishes commands, runs `run_live` for a bounded number of steps, reads the
streams back, and asserts the expected events (`corridor_preemption` signal
decisions, vehicle movement, `GREEN_CORRIDOR_ACTIVE`, …).

---

## Testing

```bash
# backend
.venv/bin/pytest services/ packages/ -q          # full suite (~460 tests)
.venv/bin/ruff check services/ packages/
.venv/bin/mypy services/sim-service/sim_service/

# frontend
cd web-app && npm test        # vitest — data-layer mappers + store reducers
cd web-app && npm run build   # tsc -b && vite build
```

New unit coverage for this layer:

| Area | Tests |
|---|---|
| routing cost model / graph / search / planner / `evaluate` | `services/sim-service/tests/routing/` |
| anomaly severity + blocked-edge handling + auto-expire | `tests/live/test_anomaly_control.py` |
| emergency request state machine + routing + recalculate + cancel | `tests/live/test_emergency_control.py` |
| green-corridor planning + `preemption_plan` shapes + interlock rejection | `tests/live/test_green_corridor.py` |
| arbiter rung-3 preemption is checked / rejected / falls back | `tests/signal_controller/test_arbiter_preemption.py` |
| corridor arm + EV spawn + in-flight reroute + no-viable-reroute holds | `tests/live/test_emergency_corridor.py` |
| continuous-monitoring triggers + cooldown + interval + hysteresis | `tests/live/test_emergency_monitoring.py` |
| frontend payload mappers + timeline accumulation + store reducers | `frontend/src/**/*.test.ts` |

The M6 anomaly-detection suite and the SUMO / arbiter / interlock property tests
are unchanged and still pass.

---

## Deliberately out of scope

- **M8 / YOLO vision detection.** The `VISION` anomaly source exists in the
  domain model; nothing produces it yet.
- **Persistence & auth.** Commands are unauthenticated; state is in-memory for
  the life of a `run_live` process. Production governance of the safety config
  (dual control, staged rollout) is described in the architecture doc, not built.
- **Analytics workspace.** The frontend page is a deliberate placeholder.
