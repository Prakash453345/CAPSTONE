# ITMS — Intelligent Traffic Management & Emergency Response Platform

Capstone implementation, built milestone by milestone against `ITMS Build Guide` v1.0
(companion to `smart-traffic-platform-architecture.md` v1.1 and
`platform-architecture-diagram.mermaid`). Those three documents are the spec; this
repo is the build. Where this README and the docs disagree, the docs win — fix the
README.

> **Console sign-in.** `/console` requires an account (PostgreSQL `app_user`
> table). Create the first one with `python -m api_service.users create <name>`;
> setup, env vars and the deployment checklist are in [`docs/auth.md`](docs/auth.md).

## Current milestone

*Updated 24 September 2026. `PROGRESS.md` has every number, every negative
result and every date; `baselines/` holds the raw runs behind the current ones.*

**M0-M3, M5 and M7 are built and measured. M6 is built but not accurate yet.
M8 (vision) is built, measured on a digital twin of the corridor's
cameras, wired into the live controller, and smoke-tested on real footage;
it has not seen Vijayawada footage.**

- **M5 — CC-A-CAMP (adaptive signal control) — done, with a caveat that has
  to travel with the headline.** On 18 September a review of the whole
  control path found four measurement defects: occupancy was divided by 100
  twice, so the spillback gate never ran; clearance intervals and minimum
  green were netconvert's guesses; throughput and the warm-up filter did not
  measure what they claimed; and the starvation bound did not follow the
  ceiling. The same day the corridor's speed limits were capped from the OSM
  road-type defaults (80-100 km/h) to 50 km/h, and a 3 s gap-out was added.
  Current baseline, `baselines/2026-09-18_gap_out/`, 10 held-out seeds,
  paired, person-delay:

  | level | vs tuned Webster (fixed-time) | vs `ceiling` arm (same controller, supervisor off) |
  |---|---|---|
  | light | **-25.0%**, significant, 10/10 seeds | -2.1%, not significant |
  | medium | **-31.2%**, significant, 10/10 seeds | 0.0%, not significant |
  | heavy | **-26.2%**, significant, 10/10 seeds | +2.4%, not significant |

  Zero interlock violations in every arm, at every level, on every seed. The
  first column is a real, large win for adaptive control over tuned
  fixed-time timing, on corrected inputs that helped Webster too. The second
  column is the caveat: **the cycle supervisor -- M5's last addition -- no
  longer shows a measurable benefit** (it was -5.5% at heavy demand on
  12 September), and since the `ceiling` arm now has zero violations too, its
  safety role isn't being demonstrated on this corridor either. The 3 s
  gap-out smooths light-demand waits and stops but does not cut delay. So
  every gain recorded on 18 September came from correcting an input, not from
  new control logic. A-CA-MP also still leans on its Webster-referenced
  max-green ceiling: without it (11 September, before these fixes, not
  re-measured since) it lost to Webster at light and medium demand. The earlier "-12.1% / -11.6% against
  Webster at heavy demand" figures predate the fixes and should not be
  quoted, and person-delay from before the speed-limit change is not
  comparable with person-delay after it (it moves SUMO's free-flow
  reference). The two candidates left to try are in
  [`docs/algorithm_improvement_research.md`](docs/algorithm_improvement_research.md).

- **M6 — anomaly detection (incident spotting) — built end to end, not yet
  accurate.** Graph-based detector, conformal alert threshold, incident state
  machine with a hash-chained audit, event schemas, ~105 dedicated tests. The
  model has only had a proof-of-training run (2 scenarios, 12 epochs): recall
  0.50 against a 0.90 target and ~0.19 false alarms per tick against <= 0.10,
  on 1 evaluation seed. No trained model ships in this checkout.
  `ITMS_M6_Anomaly_Detection_Status_and_Accuracy_Plan.docx` has the plan to
  close the gap (record the full 30-scenario dataset, train longer). The
  separate M6 on the `VIVEK` branch is not merged --
  [`docs/m6_branch_decision.md`](docs/m6_branch_decision.md) says why.

- **M7 — green corridor (emergency vehicle preemption) + dispatch — built; the
  original advantage over reactive preemption did not survive the 18 September
  fixes.** Original measurement (medium demand, 10 paired seeds, a trauma call
  through all seven signals, corridor vs field-standard reactive preemption): EV
  travel time -3.5%, time lost to signals -25.3%, stops -31.5%, worst wait -10.1%.
  **Re-run 2026-10-14 on the post-fix code** (`baselines/2026-10-14_m7_rerun`,
  `scripts/m5_artifacts/m7_corridor_gate_rerun_20261014.json`): corridor vs
  reactive is EV travel time +6.7 s [+0.01, +13.4], time lost +6.95 s
  [+0.22, +13.7], stops +0.9 (n.s.), cross-street person-delay not significant.
  Preemption itself still works (both arms cut EV time ~210-220 s vs none, zero
  interlock violations), but the corridor engine is no better than reactive
  preemption on this corridor. Do not quote the original percentages as current.
  One negative result reported honestly: the "anticipation" and
  "debt-recovery" pressure terms (Contribution 1) show no measurable benefit
  (10 paired seeds at medium demand, 30 at heavy); they stay on by default and
  are documented as unproven.

- **Live demo (`make dev`, `SIM_MODE=sumo`).** A-CA-MP governs every junction
  through `control/runner.run_controlled_scenario` -- the same path the gate
  scripts use -- cold-started, with no warmed memory profile and no EV
  preemption. M6's `LiveIncidentDetector` is wired in, and is a documented
  no-op until a trained model is dropped in. `api-service` fans every topic
  out over one WebSocket, keeps an in-memory incident registry, and exposes
  `POST /v1/incidents/{id}/confirm|reject` (ADR-006's human gate, API-key
  protected) plus read-only `GET /v1/incidents[/{id}]`.

- **Interactive emergency response (`SIM_MODE=live`).** An operator injects an
  anomaly that really affects SUMO. `IncidentResponseOrchestrator` turns a
  severe one into an alert with GPS and dispatches one unit per responding
  authority: police from real OSM police stations, ambulances based at
  hospitals (then chained on to the nearest hospital). Fire trucks have no
  depot data in this OSM extract, so they are never dispatched. Units drive
  under a dynamic anomaly-aware router, re-route continuously, and get a green
  corridor from the live `CorridorController` -- all through the same arbiter
  and interlocks. This layer is tested (68 tests in
  `services/sim-service/tests/live/`) but not benchmarked; the measured M7
  numbers above come from the separate benchmarked engine in
  `control/corridor/`, which still runs only inside scripts. Full description,
  cost formula, event contracts and a demo guide:
  **[`docs/interactive-emergency-response.md`](docs/interactive-emergency-response.md)**.

- **Not connected yet:** the M6 detector does not feed the response chain.
  Live mode dispatches from operator-marked anomalies only; the detector (in
  `sumo` mode) raises candidates for the incident inbox, not dispatches.

- **M8 — vision — built, measured on a digital twin, wired into the live
  controller, not yet on Vijayawada footage.** Junction cameras become one
  more sensor adapter: the vision service reports exactly the per-link queue
  quantities the controller already reads from SUMO, plus a confidence
  built from coverage, camera health, occlusion and queue truncation.
  SimCam films the SUMO corridor through each of 19 planned cameras with a
  detector-error model, so every stage is measured against ground truth.
  Held-out seeds, paired, after a review that fixed a round of defects and
  re-ran every gate: with an in-domain detector CC-A-CAMP on cameras is
  **+0.6 %** against the same controller on truth at medium demand (not
  significant) and +13.1 % at heavy (not significant), and beats Webster by
  **−31.0 %** and **−20.3 %** (both significant), with zero interlock
  violations. Feeding the controller's confidence ladder every camera doubt
  **hurt** until its middle rung was fixed: with no demand memory it dropped
  to a min-green cycler that cuts greens short (+28 % with a stock detector).
  It now controls on the live estimate, and passing confidence on no longer
  changes a decision unless a camera has actually failed. When a junction's cameras go dark for 30 minutes, trusting them
  costs +12.6 % (significant) and being told recovers about half; when they
  go *blind* — frames arriving, nothing detected — nothing in the camera
  system notices, but a stop-bar loop cross-check in the controller does
  and recovers about a third. `CONTROL_SENSOR=vision` runs the live
  controller on the camera stream (`make m8-live` tests it end to end over
  Redis). Phase-aware incident rules catch 19 % of in-view injected
  incidents at under 2 false alarms/h for the corridor (held-out seeds): a
  feature for M6's fusion, not a detector on their own. Stock YOLO11 runs
  end to end on real CCTV footage on a CPU (69 ms/frame; our ONNX decoder
  matches Ultralytics box for box), camera-health checks raised no false
  alarm on real clips and caught every injected fault, and evidence is
  pixelated before it is stored. On an overhead view stock weights find
  almost no vehicles. On 250 labelled Bengaluru CCTV frames, IISc's
  UVH-26-trained YOLO11-S finds 71 % of vehicles at the tracker's line
  against the stock model's 32 %, and three quarters of auto-rickshaws,
  which the stock model cannot name. With the digital twin's cameras fitted
  to it, the controller on IISc's model at 1280 px input costs +2.3 %
  (medium) and +8.0 % (heavy) against perfect data, neither significant;
  at 640 px +9.3 % and +16.8 %; the stock model +17.2 %. A fine-tune of
  IISc's model (`notebooks/m8_uvh26_finetune.ipynb`, version 2, trained in
  full precision after version 1 broke on IISc's half-precision-overflowing
  BatchNorm statistics) passed the adoption bar at 640 and 960 px. At
  640 px it finds 79 % of vehicles at precision 0.91. The controller on it
  costs +4.7 % against perfect data at medium demand, where IISc's model
  at 640 px cost +9.3 %. Heavy demand did not improve: one run in five
  jammed. Next is Vijayawada footage.
  Design: [`docs/vision_system_design.md`](docs/vision_system_design.md);
  numbers: `baselines/2026-09-25_m8_review/`,
  `baselines/2026-09-25_m8_ladder_blindcheck/`,
  `baselines/2026-09-25_m8_uvh26_detector/`,
  `baselines/2026-09-26_m8_measured_detectors/`,
  `baselines/2026-09-26_m8_finetune_v1_bn/` and
  `baselines/2026-09-27_m8_finetune_v2/`.
  - **A trained incident combiner** was tested
    (`baselines/2026-09-27_m8_incident_fusion/`). It uses each link's
    normal behaviour, contrast features and the rules' evidence.
  - With whole-lane speed and halting (SUMO's, noise-free: an upper bound)
    it catches 37–43 % of in-view incidents on fresh test seeds at under
    0.3 false alarms/h, against 11 % for the re-tuned rules.
  - With the cameras alone it catches 28 % with 1 false alarm in 15 h,
    against the rules' 11 % with 26. It missed its advance bar and was not
    adopted.

The 23 September merge commit (`9ab9a44`) records 621 Python tests and 139
web-app unit tests passing; with M8 the Python suite is 788 passed, 6 skipped
(774 at `baselines/2026-09-25_m8_ladder_blindcheck/pytest_full.txt`, plus
the Indian CCTV label-set, detector-decoding, detector-evaluation and
measured-preset tests; the two BatchNorm-check tests need torch and skip
in the project venv). A plain-language version of all of this is in
[`docs/project_status_report.md`](docs/project_status_report.md).

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

Then open the **Command Center** (`web-app/`):

```bash
cd web-app && npm install && npm run dev   # http://localhost:5173 -- landing page at /, console at /console, driver view at /drive
```

It opens on in-browser simulated data, probes `api-service`'s `/health` once,
and upgrades itself to live if the backend answers (picking a mode with the
top-bar **Data** toggle overrides that). Live, it shows the Vijayawada corridor
with A-CA-MP controlling every signal and incident candidates in the inbox --
and, under `SIM_MODE=live`, anomaly injection and emergency dispatch.
Confirming or rejecting an incident needs the API key: set `API_KEY` yourself,
or read the one api-service generates and logs on startup when it isn't set
(fine for local dev, not for anything else).

`make dev` still prints `web/index.html` -- the older single-page live map and
raw event log that `web-app/` replaced.

**Another city or road network.** Nothing is tied to the corridor.
`scenarios/build_scenario.py` makes a scenario from any SUMO network (an
OpenStreetMap export, or a generated grid, radial or random network) and
`ITMS_SCENARIO=<its directory>` points every service and gate at it; the web
map takes `VITE_MAP_CENTER`. See `scenarios/README.md`, "Any road network",
and `baselines/2026-09-30_m8_any_network/` for results on eight networks,
including Berlin and Ingolstadt.

For hands-on testing -- light/medium/heavy demand, custom origin-to-destination
scenarios, A/B run comparison, milestone checklists -- use the test lab in
`../testing_site/` (`./start.sh`, then http://127.0.0.1:8420). It runs this
code and never writes inside `itms/`.

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
│   └── geo/                   # M8: cameras, homography/RANSAC, lanes and links from the SUMO net,
│                              # coverage, calibration from lane markings
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
│   │       ├── signal_controller/   # arbitration ladder + cabinet port (M2); +lane_cache,
│   │       │                        # discharge_observer (M5); +ev_detection.py, ev_routing.py (M7)
│   │       ├── routing/             # road graph + anomaly-aware emergency router (live layer)
│   │       └── live/                # SIM_MODE=live: operator anomalies, emergency control, live
│   │                                # green corridor, incident-response orchestrator
│   ├── api-service/          # [ARCH] services 6,8-12,14,15 — incidents, dispatch, routing, corridor,
│   │                          # config, audit are the ARCHITECTURE's intended scope for this service.
│   │                          # Implemented: M1 streaming (heartbeat/vehicle-position/traffic-state)
│   │                          # + M6 incidents (consume incident.* topics, confirm/reject endpoints,
│   │                          # simple API-key auth) + POST /v1/commands (operator commands onto the
│   │                          # bus -- how the live layer's anomalies, dispatch and corridors are driven).
│   └── vision-service/       # [ARCH] services 7,18 — M8: SimCam digital twin, YOLO11/ONNX, ByteTrack,
│                              # ground-plane tracking, link-state estimator + confidence, phase-aware
│                              # incident rules, camera health, redacted evidence
├── scenarios/                 # networks + demand for real/synthetic areas; suite/ (acceptance tests) arrives M2+
│   └── networks/vijayawada/facilities.json  # M7: 103 real hospitals/clinics, extracted from OSM
├── infra/postgres/           # PostGIS schema + road-network import script
├── cases/atlas.yaml          # the case atlas, machine-readable -- header only so far
├── bench/                     # harness spec (README only); the M3 harness is scripts/bench.py
├── notebooks/                 # empty; camera calibration lives in itms_geo.lanecal / vision_service.calibrate
├── docs/                      # design write-ups too long for PROGRESS.md: the M7 hazard catalogue
│                                # (86 cataloged failure modes), the corridor algorithm design,
│                                # the dispatch/destinations design, an incident-pipeline analysis,
│                                # the interactive-response guide, the 18 Sep algorithm review, the
│                                # M6 branch decision, and a plain-language status report
├── scripts/                   # gate/benchmark/diagnostic scripts (M3-M7), one per experiment
│   └── results/                # every script's generated JSON output — never hand-edited,
│                                # regenerate by re-running the script that wrote it
├── baselines/                 # frozen, dated benchmark snapshots (results, pytest log, environment)
├── web/                       # legacy vanilla-JS pages (live map, console) -- superseded by web-app/
└── web-app/                   # TRAFFIX Command Center -- React/TS/Vite/MapLibre; landing + 6 workspaces
```

## Milestone map

| # | Milestone | Status |
|---|---|---|
| M0 | Skeleton | ✅ done |
| M1 | SUMO adapter and traffic state | ✅ done |
| M2 | Safety kernel (L0 interlocks) | ✅ done |
| M3 | Baselines and KPI harness (Webster) | ✅ done |
| M4 | CA-MP Layer 1 | ✅ done — loses to Webster; superseded by M5 |
| M5 | A-CA-MP (adaptive, with memory) + cycle supervisor | ✅ done — -25% to -31% person-delay vs tuned Webster at all three levels, zero violations; the cycle supervisor shows no measured benefit over the same controller without it (18 Sep) |
| M6 | Anomaly detection (incident spotting) | ⚠️ built + tested, model undertrained — not gate-passing yet |
| M7 | Green corridor + dispatch | ✅ built, verified safe — re-run on post-18-Sep code (14 Oct) shows no advantage over reactive preemption; original gains did not reproduce; Contribution 1 pressure terms unproven |
| — | Interactive emergency response (`SIM_MODE=live`) | ✅ built + tested, not benchmarked — anomaly → alert → police/ambulance dispatch → corridor → hospital; not yet fed by the M6 detector |
| M8 | Vision on real footage | 🟡 built and gated on a digital twin (controller keeps its win on cameras; camera failure handled); wired into the live controller; real-footage smoke test; an Indian-traffic detector (IISc UVH-26) measured on Bengaluru CCTV; no Vijayawada footage yet; incident rules weak |
| M9 | Benchmark, evaluation, site | 🟡 partial — benchmark harness, Command Center (`web-app/`), test lab (`../testing_site/`); final evaluation not written |

Full detail for each milestone (demo + gate) is in the build guide §7.
