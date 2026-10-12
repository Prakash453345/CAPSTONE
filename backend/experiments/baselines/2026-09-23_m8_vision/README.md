# Baseline — M8 vision (2026-09-23/24)

> **Superseded by [`../2026-09-25_m8_review/`](../2026-09-25_m8_review/)**: a
> review found defects that change some of these numbers (Gate 4
> under-counted false alarms; tracks survived gaps in the video; the hidden
> queue past the view over-shot; tracking scores charged boxes on vehicles
> too hidden to score), and every gate was re-run on the fixed code. This
> folder is kept as the record of the first measurement.

The first measurements of the vision system: how far camera estimates are
from SUMO truth, what CC-A-CAMP loses when it runs on cameras instead of
truth, what a camera outage costs and whether confidence earns its keep,
how well phase-aware rules find injected incidents, and a smoke test of a
real YOLO11 on real footage.

Everything below was produced by the scripts named in each section; every
table is printed by `scripts/m8_report.py` from the JSON files in this
folder, not copied by hand.

## Setup

| | |
|---|---|
| Code | branch `gap-out` + the M8 working tree (uncommitted at the time of the runs) |
| Controller | CC-A-CAMP exactly as `baselines/2026-09-18_gap_out/` (ceiling on, supervisor on, 3 s gap-out) |
| Cameras | `scenarios/networks/vijayawada/cameras.json`: 19 cameras, 10 m up, 50° hfov, 1920×1080, one per signalised approach |
| Vision | SimCam at 5 fps; detector error presets `ideal`, `finetuned_day`, `coco_pretrained`, `night_rain` |
| Seeds | held-out `EVAL_SEEDS` 1–5 (incidents: TRAIN 101–102 to choose, EVAL 1–3 to score) |
| Machine | 2 vCPU container; `environment.txt` |

The presets are **assumptions, not measurements** of any real detector on
Vijayawada footage: `finetuned_day` stands for an in-domain model (YOLO11
fine-tuned on Indian traffic), `coco_pretrained` for stock COCO weights with
the domain gap the BMD-45 paper reports. Every closed-loop number carries
the preset it was measured under.

## Gate 1 — estimates vs SUMO truth (`m8_perception_gate.py`)

One seed per cell, 1,800 steps (the first 300 s excluded), CC-A-CAMP on
truth driving the traffic while the vision system films it. File:
`perception_gate.json`.

| level | preset | queue PCU MAE / bias / corr | approaching MAE | recv. occupancy MAE | MOTA | IDF1 | det. recall car / 2W / auto | speed MAE (m/s) | lane acc. | confidence mean (<0.8) | queue truncated | candidates / h (no incident) |
|---|---|---|---|---|---:|---:|---|---:|---:|---|---:|---:|
| medium | `ideal` | 0.05 / +0.03 / 0.83 | 0.06 | 0.010 | 0.85 | 0.86 | 1.00 / 1.00 / 1.00 | 0.36 | 0.97 | 0.93 (0%) | 0.0% | 2.4 |
| medium | `finetuned_day` | 0.05 / +0.02 / 0.83 | 0.07 | 0.010 | 0.63 | 0.72 | 0.89 / 0.84 / 0.86 | 0.58 | 0.96 | 0.90 (0%) | 0.1% | 2.4 |
| medium | `coco_pretrained` | 0.08 / +0.03 / 0.78 | 0.11 | 0.010 | 0.23 | 0.53 | 0.76 / 0.68 / 0.71 | 0.92 | 0.94 | 0.86 (10%) | 0.1% | 9.6 |
| medium | `night_rain` | 0.08 / -0.03 / 0.70 | 0.11 | 0.010 | 0.05 | 0.40 | 0.57 / 0.54 / 0.57 | 1.45 | 0.94 | 0.82 (47%) | 0.1% | 12.0 |
| heavy | `ideal` | 0.40 / +0.17 / 0.81 | 0.11 | 0.019 | 0.89 | 0.89 | 1.00 / 1.00 / 1.00 | 0.27 | 0.98 | 0.93 (0%) | 1.0% | 117.6 |
| heavy | `finetuned_day` | 0.31 / -0.10 / 0.92 | 0.13 | 0.019 | 0.75 | 0.79 | 0.88 / 0.82 / 0.86 | 0.46 | 0.98 | 0.90 (0%) | 0.6% | 88.8 |
| heavy | `coco_pretrained` | 0.55 / -0.34 / 0.85 | 0.20 | 0.019 | 0.51 | 0.63 | 0.76 / 0.65 / 0.71 | 0.72 | 0.97 | 0.86 (7%) | 0.1% | 100.8 |
| heavy | `night_rain` | 0.86 / -0.74 / 0.72 | 0.21 | 0.018 | 0.33 | 0.48 | 0.56 / 0.51 / 0.56 | 1.05 | 0.96 | 0.82 (48%) | 0.1% | 81.6 |

MOTA/IDF1 are per camera, identities namespaced by camera. "Candidates / h"
are incident candidates raised by the hand-set default rules with **no
incident injected** — i.e. false alarms; Gate 4 is where the rules are
tuned.

## Gate 2 — CC-A-CAMP on cameras (`m8_closed_loop_gate.py`)

`VisionSensor` swaps the four queue-state fields in each junction's
`JunctionContext` for the camera estimate. `trust` withholds confidence,
`honest` passes every value, `failsafe` passes only values below 0.5 (a
camera that has really failed). `has_demand` and `wait_times_s` (the safety
kernel's max-wait inputs) stay ground truth. File: `closed_loop.json`.

**medium** (paired held-out seeds)

| arm | n | person-delay | p95 wait (s) | stops/veh | interlock viol. | confidence fed (mean) | fixed-time fallback |
|---|---:|---:|---:|---:|---:|---:|---:|
| `webster` | 5 | 106,912 | 83.8 | 2.24 | 0 | -- | -- |
| `truth` | 5 | 73,355 | 59.4 | 1.75 | 0 | -- | -- |
| `vision:finetuned_day:honest` | 5 | 74,728 | 65.0 | 1.78 | 0 | 0.90 | 1.9% of ticks |
| `vision:finetuned_day:trust` | 5 | 75,464 | 63.6 | 1.76 | 0 | 0.89 | 0.0% of ticks |
| `vision:coco_pretrained:honest` | 5 | 97,073 | 75.2 | 2.23 | 0 | 0.86 | 43.4% of ticks |
| `vision:finetuned_day:trust:outage` | 5 | 86,562 | 77.0 | 1.81 | 0 | 0.78 | 0.0% of ticks |
| `vision:finetuned_day:honest:outage` | 5 | 77,308 | 58.8 | 1.80 | 0 | 0.78 | 8.6% of ticks |
| `vision:finetuned_day:failsafe:outage` | 5 | 78,445 | 57.8 | 1.75 | 0 | 0.78 | 7.0% of ticks |
| `vision:coco_pretrained:failsafe` | 5 | 77,896 | 65.2 | 1.79 | 0 | 0.86 | 0.0% of ticks |

| head to head (second vs first) | person-delay | stops/veh |
|---|---|---|
| `vision:finetuned_day:honest` vs `vision:finetuned_day:trust` | -1.0% n.s., 3/5 seeds lower | +0.9% n.s., 3/5 seeds lower |
| `vision:coco_pretrained:honest` vs `vision:coco_pretrained:failsafe` | +24.6% **SIG**, 0/5 seeds lower | +24.3% **SIG**, 0/5 seeds lower |
| `vision:finetuned_day:trust:outage` vs `vision:finetuned_day:trust` | +14.7% **SIG**, 0/5 seeds lower | +2.9% n.s., 2/5 seeds lower |
| `vision:finetuned_day:honest:outage` vs `vision:finetuned_day:trust:outage` | -10.7% n.s., 4/5 seeds lower | -1.0% n.s., 3/5 seeds lower |
| `vision:finetuned_day:failsafe:outage` vs `vision:finetuned_day:trust:outage` | -9.4% n.s., 5/5 seeds lower | -3.8% n.s., 4/5 seeds lower |
| `vision:finetuned_day:failsafe:outage` vs `vision:finetuned_day:honest:outage` | +1.5% n.s., 2/5 seeds lower | -2.8% n.s., 4/5 seeds lower |

| comparison | person-delay | stops/veh |
|---|---|---|
| `truth_vs_webster` | -31.4% **SIG**, 5/5 seeds lower | -21.6% **SIG**, 5/5 seeds lower |
| `vision:coco_pretrained:failsafe_vs_truth` | +6.2% n.s., 1/5 seeds lower | +2.2% **SIG**, 0/5 seeds lower |
| `vision:coco_pretrained:failsafe_vs_webster` | -27.1% **SIG**, 5/5 seeds lower | -19.9% **SIG**, 5/5 seeds lower |
| `vision:coco_pretrained:honest_vs_truth` | +32.3% **SIG**, 0/5 seeds lower | +27.1% **SIG**, 0/5 seeds lower |
| `vision:coco_pretrained:honest_vs_webster` | -9.2% **SIG**, 4/5 seeds lower | -0.4% n.s., 3/5 seeds lower |
| `vision:finetuned_day:failsafe:outage_vs_truth` | +6.9% **SIG**, 0/5 seeds lower | -0.4% n.s., 2/5 seeds lower |
| `vision:finetuned_day:failsafe:outage_vs_webster` | -26.6% **SIG**, 5/5 seeds lower | -21.9% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:honest:outage_vs_truth` | +5.4% n.s., 2/5 seeds lower | +2.4% n.s., 1/5 seeds lower |
| `vision:finetuned_day:honest:outage_vs_webster` | -27.7% **SIG**, 5/5 seeds lower | -19.7% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:honest_vs_truth` | +1.9% n.s., 2/5 seeds lower | +1.5% n.s., 2/5 seeds lower |
| `vision:finetuned_day:honest_vs_webster` | -30.1% **SIG**, 5/5 seeds lower | -20.4% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:trust:outage_vs_truth` | +18.0% **SIG**, 0/5 seeds lower | +3.5% n.s., 1/5 seeds lower |
| `vision:finetuned_day:trust:outage_vs_webster` | -19.0% **SIG**, 5/5 seeds lower | -18.9% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:trust_vs_truth` | +2.9% n.s., 2/5 seeds lower | +0.6% n.s., 1/5 seeds lower |
| `vision:finetuned_day:trust_vs_webster` | -29.4% **SIG**, 5/5 seeds lower | -21.2% **SIG**, 5/5 seeds lower |

**heavy** (paired held-out seeds)

| arm | n | person-delay | p95 wait (s) | stops/veh | interlock viol. | confidence fed (mean) | fixed-time fallback |
|---|---:|---:|---:|---:|---:|---:|---:|
| `webster` | 5 | 648,447 | 427.0 | 3.23 | 0 | -- | -- |
| `truth` | 5 | 457,164 | 270.6 | 2.73 | 0 | -- | -- |
| `vision:finetuned_day:honest` | 5 | 582,109 | 443.4 | 3.49 | 0 | 0.90 | 0.8% of ticks |
| `vision:finetuned_day:trust` | 5 | 503,715 | 360.2 | 3.09 | 0 | 0.89 | 0.0% of ticks |

| head to head (second vs first) | person-delay | stops/veh |
|---|---|---|
| `vision:finetuned_day:honest` vs `vision:finetuned_day:trust` | +15.6% n.s., 1/5 seeds lower | +12.8% n.s., 1/5 seeds lower |

| comparison | person-delay | stops/veh |
|---|---|---|
| `truth_vs_webster` | -29.5% **SIG**, 5/5 seeds lower | -15.5% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:honest_vs_truth` | +27.3% **SIG**, 0/5 seeds lower | +27.7% **SIG**, 0/5 seeds lower |
| `vision:finetuned_day:honest_vs_webster` | -10.2% n.s., 4/5 seeds lower | +7.9% n.s., 2/5 seeds lower |
| `vision:finetuned_day:trust_vs_truth` | +10.2% n.s., 2/5 seeds lower | +13.2% n.s., 1/5 seeds lower |
| `vision:finetuned_day:trust_vs_webster` | -22.3% **SIG**, 5/5 seeds lower | -4.4% n.s., 3/5 seeds lower |

`closed_loop_honest_v1_visibility.json` holds the first `honest` runs, made
with the visibility term that counted frame-edge and never-moved tracks as
unseen (see PROGRESS.md, M8); they are superseded and kept for the record.

## Gate 3 — a camera outage (`...:outage` arms of the same gate)

All four cameras at `cluster_1880441740_4393296791` (the corridor's busiest
junction, 16 links) dark from 900 s to 2,700 s. Medium demand, the same
five seeds. In `closed_loop.json` alongside Gate 2 (the head-to-head rows
above with `:outage`).

## Gate 4 — incidents (`m8_incident_gate.py` + `m8_incident_analysis.py`)

Webster control, six incidents per run scheduled inside the run, M6's
injector (with stalled vehicles now held in their lane) and scoring. Hits
are logged at low thresholds; the operating point is chosen on TRAIN seeds
101–102 and scored once on EVAL seeds 1–3. Files: `incident_train.json.gz`,
`incident_eval.json.gz` (every logged rule hit; `m8_incident_analysis.py`
reads the `.gz` directly), `incident_analysis_budget{1,10}.json`.

**Budget 10 false alarms per hour (the `assist` operating point):**

False-alarm budget on TRAIN: 10.0 per simulated hour, whole corridor.

| | incidents | in view | recall (all) | recall (in view) | mean latency (s) | false alarms / h | by rule |
|---|---:|---:|---:|---:|---:|---:|---|
| train | 23 | 20 | 0.43 | 0.50 | 68 | 7.86 | {'flow_void': 22, 'midblock_stop': 2} |
| eval | 35 | 27 | 0.37 | 0.37 | 53 | 8.75 | {'midblock_stop': 7, 'flow_void': 33} |
| eval hand set default | 35 | 27 | 0.31 | 0.33 | 62 | 31.92 | {'midblock_stop': 10, 'stuck_on_green': 102, 'collision_cue': 33, 'flow_void': 1} |

In-view incidents by kind (eval): stall 6/14, lane_block 4/13

Chosen policy: rules midblock_stop, flow_void; persistence 5 ticks

| FA/h (train) | recall in view (train) | recall in view (eval) | FA/h (eval) | latency (eval, s) |
|---:|---:|---:|---:|---:|
| 0.00 | 0.00 | 0.00 | 0.00 | -- |
| 0.33 | 0.10 | 0.15 | 1.09 | 61 |
| 0.66 | 0.30 | 0.19 | 1.53 | 58 |
| 4.91 | 0.40 | 0.33 | 5.47 | 67 |
| 7.86 | 0.50 | 0.37 | 8.75 | 53 |
| 12.12 | 0.55 | 0.37 | 9.40 | 52 |
| 20.31 | 0.65 | 0.41 | 19.24 | 61 |
| 30.79 | 0.70 | 0.44 | 28.86 | 48 |
| 39.64 | 0.75 | 0.44 | 33.45 | 60 |

**Budget 1 per hour (`quiet`):**

False-alarm budget on TRAIN: 1.0 per simulated hour, whole corridor.

| | incidents | in view | recall (all) | recall (in view) | mean latency (s) | false alarms / h | by rule |
|---|---:|---:|---:|---:|---:|---:|---|
| train | 23 | 20 | 0.26 | 0.30 | 67 | 0.66 | {'midblock_stop': 2} |
| eval | 35 | 27 | 0.23 | 0.19 | 58 | 1.53 | {'midblock_stop': 7} |
| eval hand set default | 35 | 27 | 0.31 | 0.33 | 62 | 31.92 | {'midblock_stop': 10, 'stuck_on_green': 102, 'collision_cue': 33, 'flow_void': 1} |

In-view incidents by kind (eval): stall 5/14, lane_block 0/13

Chosen policy: rules midblock_stop; persistence 5 ticks

| FA/h (train) | recall in view (train) | recall in view (eval) | FA/h (eval) | latency (eval, s) |
|---:|---:|---:|---:|---:|
| 0.00 | 0.00 | 0.00 | 0.00 | -- |
| 0.33 | 0.10 | 0.15 | 1.09 | 61 |
| 0.66 | 0.30 | 0.19 | 1.53 | 58 |

Earlier versions of this gate are kept in `superseded/`: before the
injector held stalls in lane and before stopped-track stitching
(`*_prestitch*`: held-out 0.26 at 8.1/h), and with stitching but the
lane-hopping injector (`incident_train_stitch_lanehop.json.gz`).

**Spot check — what stitching does to Gate 1** (`perception_stitch_check.json`,
`finetuned_day`, same seed): queue MAE 0.051 → 0.063 PCU at medium,
0.309 → 0.304 at heavy. Gates 1–3 were run before stitching.

## Real footage (`m8_real_video_smoke.py`)

Stock `yolo11n.pt` (COCO), CPU only, on short public clips. Folder
`real_video/`.

| clip | what | detector | tracks | camera health on the clean clip | faults caught (applied to the second half) |
|---|---|---|---|---|---|
| `overpass.mp4` (640×352, 24 fps, 905 frames) — a two-way street approaching a junction, pole camera | 69 ms/frame (PyTorch), 94 ms/frame (our ONNX path); ONNX boxes identical to Ultralytics: 4,717 / 4,717, IoU 0.999999 | 16 tracks, none shorter than 1 s, median 6.1 s; 1 parked car flagged stationary | 0 alarms in 855 frames | blur, covered lens, fog, underexposure: immediately; frozen feed: 1.0 s |
| `pbc.mp4` (768×432, 12 fps, 647 frames) — car park from above, cars, people, a cyclist | 71 ms/frame | 8 tracks (4 person, 2 car, 2 bicycle) | 0 alarms in 597 frames (after the relative-contrast fix; the absolute threshold flagged 474) | all five; frozen: 2.1 s |
| `highway.avi` (320×176, overhead) | stock YOLO11 n/s/m | vehicles in 43 of 75 sampled frames; the three models returned 2, 3 and 1 vehicle boxes. The 85 "airplane" boxes from yolo11n all sit on road paint (they appear on the empty-road image too) | — | — |

Images: `overpass_tracks.jpg`, `pbc_tracks.jpg` (drawn on redacted frames),
`pbc_redacted_evidence_frame.jpg` (what an evidence clip stores). Clip
sources: `intel-iot-devkit/sample-videos` (`person-bicycle-car-detection.mp4`),
`ahmetozlu/vehicle_counting_tensorflow` (`input_video.mp4`),
`andrewssobral/simple_vehicle_counting` (`dataset/video.avi`). The clips
are not committed.

## Reproducing

```bash
cd itms && make setup
.venv/bin/python scripts/m8_perception_gate.py --presets ideal,finetuned_day,coco_pretrained,night_rain \
    --levels medium,heavy --seeds 1 --max-steps 1800 --out perception_gate.json
.venv/bin/python scripts/m8_closed_loop_gate.py --levels medium,heavy --seeds 5 \
    --arms webster,truth,vision:finetuned_day:honest,vision:finetuned_day:trust --out closed_loop.json
.venv/bin/python scripts/m8_closed_loop_gate.py --levels medium --seeds 5 --resume --out closed_loop.json \
    --arms truth,vision:coco_pretrained:honest,vision:coco_pretrained:failsafe,vision:finetuned_day:trust:outage,vision:finetuned_day:honest:outage,vision:finetuned_day:failsafe:outage
.venv/bin/python scripts/m8_incident_gate.py --levels medium,heavy --seeds 2 --seed-set train --no-twins --out incident_train.json
.venv/bin/python scripts/m8_incident_gate.py --levels medium,heavy --seeds 3 --seed-set eval --no-twins --out incident_eval.json
.venv/bin/python scripts/m8_incident_analysis.py incident_train.json incident_eval.json --budget 10 --out incident_analysis_budget10.json
.venv/bin/python scripts/m8_report.py --closed-loop closed_loop.json --perception perception_gate.json \
    --incidents incident_analysis_budget10.json
pip install -e 'services/vision-service[yolo,onnx]'
.venv/bin/python scripts/m8_real_video_smoke.py --video overpass.mp4 --onnx --redact-demo --out real_video/overpass
```

Wall time on 2 vCPU: about 5 h for everything above (a heavy vision run is
~5 min, a medium one ~3.5 min, a truth run under a minute).

## Code version per gate

The runs span a day in which the gates themselves found three defects, each
fixed and tested before the numbers that depend on it were re-measured:

| change | affects | gates run with it |
|---|---|---|
| visibility counts only in-frame vehicles that drove in | confidence | 1, 2 (`honest`, `failsafe` arms — the `trust` arm never reads confidence), 3, 4 |
| a failed camera no longer blinds lanes another camera sees | confidence under camera failure | 3 (no camera fails anywhere else) |
| stopped-track stitching | stop duration and "drove in" of re-acquired stopped vehicles | 4; see the spot check in Gate 4 for its effect on Gate 1's numbers |
| contrast judged against the camera's own baseline | pixel health on real frames | real footage (SimCam does not render pixels) |
