# ITMS — Intelligent Traffic Management & Emergency Response Platform

Capstone implementation, built milestone by milestone against `ITMS Build Guide` v1.0
(companion to `smart-traffic-platform-architecture.md` v1.1 and
`platform-architecture-diagram.mermaid`). Those three documents are the spec; this
repo is the build. Where this README and the docs disagree, the docs win — fix the
README.

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

- **M7 — green corridor (emergency vehicle preemption) + dispatch — done,
  measured, due a re-run.** Against field-standard reactive preemption at
  medium demand, 10 paired seeds, a trauma call routed through all seven
  signals: EV travel time -3.5%, time lost to signals -25.3%, stops -31.5%,
  worst individual wait -10.1%, all significant; cross-street person-delay
  +1.6%, not significant. **These were measured before the 18 September
  fixes** (the occupancy bug reached the corridor engine's `rho_couple` test,
  and clearance, minimum green and speed limits all changed underneath it), so
  re-run `scripts/m7_corridor_benchmark.py` before quoting them as current.
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

All commands run from `backend/`. Requires Python 3.11+ (3.13 is what the team
uses); Docker + `make` for the full stack, or Redis alone for the Windows script.

**Windows, no Docker** (what the team uses day to day):

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pip install -e libs/domain -e libs/common -e libs/geo `
    -e services/simulation-service -e services/api-gateway -e services/vision-service
powershell -File scripts\dev-local.ps1              # redis + api-gateway + simulation (live mode)
powershell -File scripts\dev-local.ps1 -WithVision  # ... + the video clip worker
```

**With Docker** (postgres+postgis+timescale, redis, minio):

```bash
make dev         # infra up, then simulation-service + api-gateway
make test        # full suite except the M6 anomaly-detector tests (they need the
                 # optional [anomaly] extra -- see test-anomaly below); includes
                 # the ~55s, 10,000-example-per-invariant safety property suite
make test-fast   # same as test, minus that slow property suite -- quick dev loop
make test-anomaly # installs numpy/torch and runs just the M6 detector tests
make test-all    # everything, including the anomaly extra
make lint        # ruff + mypy
make down        # stop the stack
```

Then the **Command Center** (`../frontend/`):

```bash
cd ../frontend && npm install && npm run dev   # http://localhost:5173 -- landing page at /, console at /console
```

It opens on in-browser simulated data, probes the api-gateway's `/health`
once, and upgrades itself to live if the backend answers (the top-bar **Data**
toggle overrides that). Live, it shows the Vijayawada corridor with A-CA-MP
controlling every signal and incident candidates in the inbox -- and, under
`SIM_MODE=live` (the Windows script's default), anomaly injection, emergency
dispatch and video-clip checks. Confirming or rejecting needs the API key: set
`API_KEY` yourself, or read the one the api-gateway generates and logs at
start-up (fine for local dev, not for anything else). Interactive API docs:
http://localhost:8000/docs.

**Video incident detection** needs the trained models in `data/models/`
(not in git; ask the vision owner): `itms_six_aug_640.onnx` (vehicles),
`itms_fire_640.pt` + `itms_fire_cls_112.onnx` (fire/smoke, needs the
`[fire]` extra), `itms_accident_224.onnx` (accidents, from
`ml/notebooks/m8_accident_step1_train.ipynb`). The worker
(`python -m vision_service.clips`) logs which detectors are on.

**Another city or road network.** Nothing is tied to the corridor.
`data/scenarios/build_scenario.py` makes a scenario from any SUMO network (an
OpenStreetMap export, or a generated grid, radial or random network) and
`ITMS_SCENARIO=<its directory>` points every service and gate at it;
`SIM_NETWORK=district` picks the built-in Vijayawada district grid instead of
the corridor. The web map takes `VITE_MAP_CENTER` / `VITE_ITMS_NETWORK`. See
`data/scenarios/README.md` and `experiments/baselines/2026-09-30_m8_any_network/`.

To load the road network into PostGIS (separate from the SUMO scenario files,
which the simulation service reads directly):

```bash
.venv/bin/python infra/postgres/import_road_network.py \
  --geojson data/scenarios/networks/vijayawada/vijayawada_corridor.geojson \
  --network-name vijayawada_corridor
```

## Why it's built this way

The core architectural bet, from the architecture doc: **every data source is an
adapter behind a common event contract.** `contracts/events/` is that contract. All
services import from it; nothing hand-rolls its own event shape. This is cheap now
and expensive to retrofit later, so it exists from milestone zero -- `SystemHeartbeat`
(M0), then `VehiclePositionUpdated` / `ApproachState` (M1), growing one milestone
at a time.

Phase 1 collapses the 20-service catalog from the architecture doc into three
deployables -- `simulation-service`, `api-gateway`, `vision-service` -- with Redis
Streams standing in for Kafka. They share code only through `libs/` and talk only
through the bus, so extracting more services later is mechanical. Internal module
boundaries mirror the full service catalog.

Every file location (scenarios, models, contracts, results, runtime state) is
defined once, in `libs/domain/itms_domain/paths.py`; nothing counts parent
folders from its own file.

## Layout

```
backend/
├── pyproject.toml, requirements-dev.txt, Makefile
├── services/                      # deployable services
│   ├── api-gateway/               # FastAPI: the console's one HTTP/WebSocket entry point
│   │   └── api_gateway/
│   │       ├── main.py            # create_app(): settings, state, routers, lifespan
│   │       ├── core/              # config (env settings), security (API key)
│   │       ├── api/routes/        # controllers: health, commands, stream, incidents, clips
│   │       ├── services/          # incident + clip registries, bus -> WebSocket relay
│   │       └── models/            # request bodies, stored records
│   ├── simulation-service/        # SUMO, signal control, routing, live emergency layer
│   │   └── sim_service/
│   │       ├── adapters/sumo/       # TraCI loop (M1)
│   │       ├── control/safety/      # L0 interlocks -- pure predicates (M2)
│   │       ├── control/strategies/  # fixed_time (M2); webster/actuated (M3); camp (M4); acamp (M5)
│   │       ├── control/anomaly/     # M6: graph autoencoder, conformal calibration, fusion
│   │       ├── control/corridor/    # M7: green corridor engine
│   │       ├── control/dispatch/    # M7: hospital-destination routing
│   │       ├── signal_controller/   # arbitration ladder + cabinet port
│   │       ├── routing/             # road graph + anomaly-aware emergency router
│   │       └── live/                # SIM_MODE=live: operator anomalies, emergency control,
│   │                                # green corridor, incident-response orchestrator
│   └── vision-service/            # M8: SimCam digital twin, detectors, tracking, link state,
│       └── vision_service/        # incident rules, fire; clips/ = uploaded-video detection
├── libs/                          # shared packages (no service depends on another service)
│   ├── domain/                    # entities, state machines, safety-kernel types, paths
│   ├── common/                    # event bus client + Avro envelope (Redis Streams, ADR-003)
│   └── geo/                       # camera geometry, lanes from the SUMO net, calibration
├── contracts/events/*.avsc        # ONE event language, shared by all services
├── data/
│   ├── scenarios/                 # SUMO networks + demand (Vijayawada corridor and district,
│   │                              # generated networks), facilities, cameras
│   └── models/                    # trained weights -- not in git
├── ml/notebooks/                  # Colab training notebooks (detectors, fire, accident)
├── experiments/                   # gate / benchmark / diagnostic scripts, one per experiment
│   ├── results/                   # their generated JSON -- regenerate, never hand-edit
│   ├── baselines/                 # frozen, dated snapshots (results, logs, environment)
│   └── bench/, cases/             # harness spec, case atlas
├── infra/                         # docker-compose.yml, postgres schema + road import
├── scripts/                       # dev tooling: dev-local.ps1, dev.sh, wait-for-healthy.sh
└── var/                           # runtime state (uploaded clips) -- not in git
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
| M7 | Green corridor + dispatch | ✅ done, verified — numbers predate the 18 Sep fixes and need a re-run; Contribution 1 pressure terms unproven |
| — | Interactive emergency response (`SIM_MODE=live`) | ✅ built + tested, not benchmarked — anomaly → alert → police/ambulance dispatch → corridor → hospital; not yet fed by the M6 detector |
| M8 | Vision on real footage | 🟡 built and gated on a digital twin (controller keeps its win on cameras; camera failure handled); wired into the live controller; real-footage smoke test; an Indian-traffic detector (IISc UVH-26) measured on Bengaluru CCTV; no Vijayawada footage yet; incident rules weak |
| M9 | Benchmark, evaluation, site | 🟡 partial — benchmark harness, Command Center (`../frontend/`), test lab (`../docs/archive/testing_site/`); final evaluation not written |

Full detail for each milestone (demo + gate) is in the build guide §7.
