# vision-service

`[ARCH]` services 7 (Vision Service) and 18 (Camera Ingestion Adapter) --
**M8**. Junction CCTV turned into the per-link traffic state the signal
controller already consumes, plus a phase-aware incident stream for M6.

The design, and why it is shaped this way, is in
[`docs/vision_system_design.md`](../../docs/vision_system_design.md). The
measured results are in `PROGRESS.md` (M8) and
`baselines/2026-09-25_m8_review/` (the first measurement, and the real-footage
smoke test, are in `baselines/2026-09-23_m8_vision/`).

## The idea in one paragraph

A camera is just another sensor adapter. It reports exactly what
`QueueStateSampler` reports from SUMO -- `queue_pcu`, `approaching_pcu`,
`receiving_occupancy`, `receiving_queue_pcu` per link `L{i}` -- plus the one
thing SUMO never had to: a **confidence** built from causes you can point to
(how much of the lane is seen at usable resolution, camera health, occlusion,
how long a queue has run past the edge of the frame). The controller's
existing degradation ladder finally gets a real number. Everything is
measured first against a **digital-twin camera** (SimCam) that films the
SUMO corridor through each real camera's geometry, with exact ground truth.

## Pipeline

```
per camera                                     central
FrameSource (RTSP | file | SimCam)             LinkStateEstimator  -> vision.link-state
  -> Detector (YOLO11 | ONNX | twin errors)      coverage, dedup, clutter map,
  -> ByteTrack (image, 2-stage)                  LWR truncation, confidence
  -> GroundTracker (Kalman in metres,          IncidentEngine (phase-aware) -> anomaly.updated
     footprint, speed, stop hysteresis)        CameraHealth (pixels + drift) -> vision.camera-status
  -> lane assignment                           Evidence (redacted, on candidate only)
```

| package | |
|---|---|
| `classes`, `records` | ITMS classes and PCU (IRC SP:41, same as `assign_vtypes.py`); `Detection`, `ImageTrack`, `GroundTrack` |
| `cameras`, `placement` | the registry (`scenarios/networks/vijayawada/cameras.json`), `CameraRig` coverage, one-camera-per-approach planner |
| `simcam` | world snapshots from TraCI or the position stream, 5 fps interpolation, cuboid projection with occlusion, the `PerceptionErrorModel` (presets `ideal`, `finetuned_day`, `coco_pretrained`, `night_rain`, and `uvh26_640`, `uvh26_1280`, `stock_640`, `itms6_640`, `itms6_960` fitted to measured detectors: bursty misses, sticky class confusion, a size curve per vehicle type, jitter, ghosts, detector hotspots) |
| `detect` | `UltralyticsDetector`, `OnnxDetector` (own letterbox/decode/NMS, no torch); a model with several types per ITMS class (UVH-26, BMD-45) has its scores summed per class before threshold and NMS; `batchnorm_health` and a load-time warning for a model file whose BatchNorm statistics are non-finite or clipped by a half-precision save (IISc's release is) |
| `track` | ByteTrack from scratch (Hungarian with component decomposition) |
| `ground` | image tracks -> metres: footprint correction, border handling, batched Kalman, lanes |
| `state` | `LinkStateEstimator` -- the `QueueSample` fields and their confidence |
| `incidents` | `stuck_on_green`, `midblock_stop`, `wrong_way`, `collision_cue`, `flow_void`; no person rule (ADR-006) |
| `health` | sharpness, exposure, frozen frames, edge collapse; calibration drift from traffic headings; an activity check (no vehicles where there is traffic) |
| `privacy` | pixelation of people, riders and plates; in-memory evidence ring; retention-bounded store (MinIO optional) |
| `sim/closed_loop` | `VisionSensor`: wraps any controller so it runs on camera state instead of SUMO's (`itms_domain.camera`, shared with the live adapter); `failsafe` by default, with the stop-bar cross-check for blind cameras; `VisionLoop.stopbar` emulates the loops |
| `eval` | CLEAR-MOT / IDF1, MOT-file evaluation, twin-vs-truth recorder, still-image detector scoring in the ITMS taxonomy (`detection`) |
| `calibrate` | point-correspondence calibration CLI (see also `itms_geo.lanecal`) |
| `service`, `main` | the running service |

## Running it

```bash
make setup
make dev            # sim-service + api-service, as before
make vision-dev     # in another shell: SimCam mode on the live position stream
```

`VISION_MODE=video` reads every registry camera whose `source` is a file or
`rtsp://` URL through a real detector (`pip install -e
'services/vision-service[onnx]'`). The default detector is fine-tune v3 of
IISc's UVH-26 model, `data/models/itms_six_aug_640.onnx` (v2 plus degradation
augmentation; `make vision-model` copies it from the fine-tune results;
`baselines/2026-10-04_m8_finetune_v3/`; v2 is `itms_six_fp32_640.onnx`); `VISION_DETECTOR` picks another
(`yolo11n.pt` is the stock COCO model). Fire and smoke detection switches on by itself when `data/models/itms_fire_640.pt` (the v4 detector) and `data/models/itms_fire_cls_112.onnx` (the Step 2 crop classifier) are both there, needs `pip install -e 'services/vision-service[fire]'`, and is turned off with `VISION_FIRE=0`; its candidates are for an operator to confirm. SimCam mode's default error preset,
`itms6_640`, is the one fitted to that detector. A source
may name environment variables (`rtsp://${CAM_USER}:${CAM_PASS}@10.0.0.12/s1`)
so the registry holds no password; logs show URLs with the user-info
masked. A detector slower than the cameras skips frames (the newest frame
per camera is processed, stamped with its capture time); a file plays at
its own speed. Other settings: `VISION_REGISTRY`, `VISION_NET`,
`VISION_PRESET`, `VISION_FPS`, `VISION_RULES`, `VISION_EVIDENCE` (a
directory for redacted evidence; `MINIO_ENDPOINT` and keys send it to MinIO
instead; unset keeps none), `REDIS_URL`.

**The controller on cameras, live:** run sim-service with
`CONTROL_SENSOR=vision` (and optionally `VISION_CONFIDENCE`, default
`failsafe`) next to this service; `scripts/m8_live_e2e.sh` does both over a
throwaway Redis and checks the link state reached the controller.

Events: `LinkStateEstimated` on `vision.link-state`, `CameraStatus` on
`vision.camera-status` (both new Avro contracts), and vision candidates as
the existing `AnomalyUpdated` with `source=VISION`.

## Experiments

| | |
|---|---|
| `make m8-perception` | estimates vs SUMO truth, by preset and demand |
| `make m8-closed-loop` | CC-A-CAMP on cameras vs on truth vs Webster, paired seeds; confidence modes `trust` / `honest` / `failsafe`; `...:outage` arms black out a junction's cameras, `...:blind` ones blind their detector (`:nocheck` without the stop-bar cross-check) |
| `make m8-incidents` | M6's injector and scoring; thresholds chosen on TRAIN seeds, reported on EVAL |
| `make m8-video VIDEO=clip.mp4` | real detector on real footage: speed, ONNX parity, tracks, health, redaction |
| `scripts/m8_fetch_uvh26_sample.py` + `scripts/m8_detector_eval.py` | UVH-26's Indian-traffic YOLO11 vs stock weights on labelled Bengaluru CCTV frames: AP50, recall / precision per class, confusions, PCU error, CPU time (`baselines/2026-09-25_m8_uvh26_detector/`) |
| `scripts/m8_detector_compare.py` | two detectors on the same frames, image by image, with bootstrap intervals and the adoption bar |
| `scripts/m8_simcam_calibrate.py` | fits SimCam's error model to a measured detector (`baselines/2026-09-26_m8_measured_detectors/`) |
| `notebooks/m8_uvh26_finetune.ipynb` | Colab: fine-tunes IISc's model to the six vehicle types, test frames kept out; version 2 keeps BatchNorm statistics in full precision and exports a repaired-only control. Its 640 and 960 px models are the adopted detectors (`baselines/2026-09-27_m8_finetune_v2/`) |
| `scripts/m8_notebook_dryrun.py` | runs that notebook's cells on CPU against a small fake repository: every edge case, a disconnect and resume, the fallbacks |
| `notebooks/m8_fire_smoke.ipynb` | Colab: a two-class fire and smoke detector (YOLO11-S) on D-Fire plus Bengaluru frames with no fire; alarm threshold chosen on validation, test scored once |
| `scripts/m8_fire_eval.py` | that detector's false alarms on the 250 Bengaluru test frames, against the bar set in advance (≤ 1 %) |
| `scripts/m8_fire_notebook_dryrun.py` | runs the fire notebook's cells on CPU against a fake D-Fire |

## Tests

`make test-vision` (or `pytest packages/geo services/vision-service`): 168 tests (2 need torch and skip without it).
