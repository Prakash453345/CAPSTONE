# M8 — The vision system: design

*Written 23 September 2026, before the first line of M8 code, and revised the
same day after the build: §9 lists every place the build departed from the
first draft and why. The measured results live in `PROGRESS.md` (M8) and
`baselines/2026-09-25_m8_review/` (which supersedes
`baselines/2026-09-23_m8_vision/`); where this document and a measurement
disagree, the measurement wins and this document gets fixed.*

This is the design for ITMS's "eyes": fixed junction CCTV turned into the
per-link traffic state the signal controller consumes, plus a phase-aware
incident stream for the M6 fusion layer. It is built against three things
that already exist and constrain it:

- **The controller's inputs.** `QueueStateSampler` (`signal_controller/
  queue_state.py`) defines, per link `L{i}`, `queue_pcu`, `approaching_pcu`,
  `receiving_occupancy` and `receiving_queue_pcu`; `JunctionContext.confidence`
  drives A-CA-MP's degradation ladder (`>= 0.8` full, `>= 0.5` blended,
  below that fixed-time). Nothing has ever fed that ladder a real number.
- **The M6 plan's Stream 2.** YOLO11 + ByteTrack feeding deterministic,
  phase-aware rules — stationary duration, deceleration, wrong-lane heading,
  stop clustering — fused with live signal state, into the `vision_score`
  slot `control/anomaly/fusion.py` already reserves.
- **ADR-006 and ARCH §21.** Vision may confirm a stopped vehicle on its own
  and must never infer human behaviour; per-vehicle positions are never
  persisted.

---

## 1. Principles

1. **Sensor equivalence.** A camera is an adapter (ADR-001). It reports the
   same quantities, in the same units, keyed the same way, as the SUMO
   sampler does. The controller cannot tell where a number came from — so
   every existing strategy runs on camera data with zero changes, and the
   difference between "controller on truth" and "controller on cameras" is
   directly measurable.
2. **Ground plane first.** Pixels are converted to metres on the road exactly
   once, at the boundary. Tracks, speeds, queues, lanes and incident rules all
   live in network coordinates (SUMO's projected metres, which map to
   lat/lon through the net's own projection). Perspective never leaks past
   the projector.
3. **Unseen is not empty.** Every estimate carries a confidence built from
   causes you can point at: how much of the lane the cameras actually see at
   usable resolution, camera health, occlusion, and how long a queue has been
   running past the edge of the view. A lane no camera sees reports
   confidence 0, never "0 vehicles".
4. **Auditable incident logic.** No black-box "accident classifier". Every
   vision score decomposes into named rules with evidence (track ids, stop
   durations, the signal state at the time).
5. **Vehicles only.** People are detected so they can be blurred, and for
   nothing else. No face or plate recognition, no person-based rule.
6. **Measurable before deployable.** A digital-twin camera films the SUMO
   corridor through each real camera's geometry with exact ground truth, so
   every stage — and the controller's delay under perception error — is
   measured with the project's paired-seed discipline before any real feed
   exists.

---

## 2. Where the cameras are

One camera per signalised approach, mounted at the stop line, about 10 m up,
**looking outward along the arm**. From there it sees:

- the approach lanes, queue head first — where `queue_pcu` and
  `approaching_pcu` live;
- the departure lanes of the same arm, near end first — the start of each
  receiving lane, which is exactly where spillback into the junction starts.

`vision_service/placement.py` generates this layout from the SUMO network:
one camera per approach edge of every traffic-light junction (setback and
pitch searched per camera), maximising the metres of lane seen at better
than **0.6 m/pixel** along the worst image direction. That limit is where a
1080p, 50° camera 10 m up is about 110 m from the road point it looks at; a
stopped car there is still a box roughly 30 px wide and 35 px tall (its
height projects far better than its foreshortened length), which a YOLO11
model at 1280 input detects. The first draft's 0.35 m/pixel would have
stopped the same camera's coverage at roughly 85 m. For the
Vijayawada corridor the planner writes 19 cameras to
`scenarios/networks/vijayawada/cameras.json`: all 40 approach lanes seen from
the stop line back, 96.8 m on average, and 17 of 38 receiving lanes seen from
their start.

A real deployment replaces each pose with a calibration, two ways
(`packages/geo/README.md`): point correspondences to surveyed ground points
(`python -m vision_service.calibrate`), or **the lane markings already in
the frame** (`itms_geo.lanecal`: lane lines with their offsets, four dash
starts, and the stop line). Nothing downstream changes.

---

## 3. The pipeline

```
 per camera (edge node)                          central (vision-service)
 ─────────────────────                           ────────────────────────
 FrameSource ─► HealthMonitor                     LinkStateEstimator
 (RTSP | file | SimCam)                             fuse all cameras per lane
      │                                             coverage + truncation
      ▼                                             ─► LinkStateEstimated event
 Detector (YOLO11 | ONNX | twin)                    ─► JunctionContext (closed loop)
      │  ITMS classes + PCU                       IncidentRules (phase-aware)
      ▼                                             ◄── SignalChanged
 ByteTrack (image space)                            ─► vision_score per link → M6 fusion
      │                                             ─► AnomalyUpdated(source=VISION)
      ▼                                           Evidence (redacted, on candidate only)
 GroundProjector ─► GroundTrack (Kalman, metres)    ─► MinIO, retention-bounded
      │  lane association, heading, stopped state
      └──────────── TrackBatch ─────────────────►
```

The split matters for deployment: everything left of the arrow can run on a
small edge device at the junction and ships only anonymous ground tracks —
no pixels leave the junction except redacted evidence.

### 3.1 Classes

ITMS classes: `motorcycle`, `car`, `auto_rickshaw`, `bus`, `truck`,
`bicycle`, `person`. PCU values are the same IRC SP:41 priors
`assign_vtypes.py` uses (0.3 / 1.0 / 0.6 / 3.0 for the four simulated
classes), so a camera-derived `queue_pcu` and the SUMO one mean the same
thing. COCO-pretrained YOLO has no auto-rickshaw class — it mostly calls them
cars or motorcycles — which is why the M6 plan names BMD-45 fine-tuning, and
why the error model's `coco_pretrained` preset carries that confusion.

### 3.2 Detection

`Detector` is a protocol with three implementations: Ultralytics YOLO11
(best on a Mac or a GPU box), ONNX Runtime (portable, no torch), and the
twin detector SimCam provides. All three emit the same `Detection` records.

A model trained on Indian CCTV names more types than the taxonomy has:
UVH-26 and BMD-45 split a car five ways (hatchback, sedan, SUV, MUV, van)
and a bus three. Such a model spreads its confidence over the types, so the
scores are summed per ITMS class before the tracker's threshold and before
NMS; thresholding the best single type dropped three in ten of the cars
the model had found. Measured on 250 UVH-26 validation frames
(`baselines/2026-09-25_m8_uvh26_detector/`): UVH-26's YOLO11-S finds 71 %
of vehicles at the tracker's line (precision 0.92, 58 ms a frame on a
laptop CPU) against the stock model's 32 %, and recognises 75 % of
auto-rickshaws, which the stock model cannot name at all.

**IISc's model file has broken BatchNorm statistics.** 584 of its 14,992
BatchNorm channels store an infinite variance. Re-estimated, the largest
true variances reach about 2.5 × 10⁷, far past half precision's largest
number (65,504), and Ultralytics saves checkpoints in half precision. At inference, an infinite
variance switches a channel off. A variance clipped to 65,504, which is
what a later half-precision save does, normalises it wrongly. The measured
numbers above are for the model as released. Re-estimating the statistics
in full precision changes its detections. A diagnostic on half the test
frames, repaired through Ultralytics' training pipeline, gave:
- precision 0.90 → 0.93;
- vehicles found 0.71 → 0.74;
- false boxes per image 0.94 → 0.70.

`UltralyticsDetector` now logs a warning for such a file
(`batchnorm_health`). Fine-tuning has to keep these numbers in full
precision (`baselines/2026-09-26_m8_finetune_v1_bn/`).

**Fine-tuning.** `notebooks/m8_uvh26_finetune.ipynb` (Colab) fine-tunes
the model to the six ITMS types on 3,000 UVH-26 training frames, keeping
the test frames and their cameras out. Version 1 of the notebook trained in
mixed precision. Its losses were `nan`, and it stopped learning after
epoch 17 (640 px) and epoch 7 (960 px). Even so, at 640 px it found more
vehicles than IISc's model (0.711 → 0.820) with a smaller PCU error, but
its precision fell to 0.876. That misses the 0.90 bar set in advance, so it
was not adopted. Version 2 trained in full precision from repaired
statistics, and passed the same bar at both input sizes, so it is the
adopted detector (`baselines/2026-09-27_m8_finetune_v2/`):
- at 640 px, vehicles found 0.711 → 0.790, precision 0.914, PCU error per
  image 2.63 → 2.02, 51 ms a frame on the laptop;
- at 960 px, vehicles found 0.775 → 0.823, precision 0.851 → 0.908.

At 640 px it more than doubles what IISc's model finds among boxes 20–40 px
tall (0.19 → 0.44). IISc's model with only its statistics repaired finds
more too, but did not pass the bar at either size.

### 3.3 Tracking

ByteTrack, implemented here rather than imported: constant-velocity Kalman on
`(cx, cy, aspect, height)`, two-stage association (high-confidence boxes
first, then low-confidence boxes against tracks the first stage left
unmatched — that second stage is what keeps a vehicle alive while a bus half
hides it), optimal assignment by the Hungarian method. About 300 lines of
numpy, fully tested, no `lap`/`cython_bbox` dependency.

### 3.4 Onto the ground

The ground contact point of a box is its bottom-centre, projected through the
camera's ground homography. That point is the vehicle's *nearest* ground
edge, not its centre; the projector shifts it half a class-typical length
along the viewing direction. Each projected point carries its local ground
resolution (m/pixel), which scales the measurement noise of a second Kalman
filter that runs in metres and produces speed and heading. "Stopped" is a
hysteresis: below 0.8 m/s held for 1 s to stop, above 2.0 m/s to move again —
not SUMO's 0.1 m/s, which no camera can resolve at 100 m.

Three details that each fixed a measured error:

- **Boxes cut by the frame edge are predicted, not measured.** A vehicle
  half out of frame has a bottom-centre that slides along the border; fed
  to the filter as a measurement it reads as a vehicle slowing down.
- **Velocity is seeded from two clean measurements** at least 0.35 s apart,
  and `speed_known` stays false until then. Before that the filter's zero
  prior is not a measurement, and the estimator does not read it as
  "stationary" (it was producing phantom queue heads).
- **`moved_m` counts only distance travelled at ≥ 1.5 m/s.** A detector
  hotspot jitters by a metre or two and would otherwise accumulate "travel".
  A track that never moved is furniture — a billboard, a parked auto — not a
  queue.
- **A stopped vehicle that is lost and re-found is the same vehicle.** When
  a new track is born within 3 m of where a stopped track was lost less
  than 10 s earlier, it inherits that track's history (metres driven,
  stopped-since). Without this, a stalled car the tracker loses behind a
  passing bus comes back with `moved_m = 0` — furniture — and no rule can
  ever see it stall. The inherited stop only takes effect once the re-found
  vehicle is itself confirmed slow by the hysteresis: the first version
  applied it at once. Slow-moving tracks (under 2 m/s) are stitched too,
  by where they would have crept to. What stitching costs the queue
  estimate, measured by switching it off: nothing on the two TRAIN seeds
  (medium, in-domain detector: 0.0500 → 0.0496 and 0.0474 → 0.0472 PCU;
  heavy: 0.747 → 0.747 and 0.390 → 0.393), but about +0.01 PCU on
  held-out seed 1 at medium: there it keeps more re-acquired vehicles out
  of the furniture filter, and the queue count rises above the truth. It
  stays: it is what lets the incident rules see a stall at all.
- **A gap in the video starts tracking afresh.** When frames stop for longer
  than the tracker's 3 s buffer — a stream that dropped, a camera that was
  dark — every vehicle after the gap is a new vehicle. The first version
  carried tracks across: ByteTrack counts its buffer in frames, so a box
  lost just before a half-hour outage was still "recent" on the first frame
  after it, and a car queued on the same spot inherited a stop that began
  half an hour earlier — a stalled-vehicle alarm on recovery. Track ids keep
  counting, so none is ever reused.

### 3.5 Lanes and links

`itms_geo.road.RoadNetwork` reads lane centrelines and widths from the SUMO
net. A ground point is assigned to the lane whose centreline it is laterally
closest to, among lanes whose direction agrees with the track's heading
(a stopped vehicle keeps its last confident lane). For lane-free Indian
traffic the per-lane split is noisy; the approach-level total is what the
controller's pressure mostly depends on, and the per-lane error is reported
separately so the difference is visible.

### 3.6 Link state and confidence

Per lane, from every camera that sees it, the estimator computes stopped PCU,
approaching PCU (moving, time-to-stop-line within the controller's 8 s
horizon), occupancy of the observed length, and the back of the queue. It
then builds each link's `QueueSample` fields exactly as `QueueStateSampler`
does — the approach lane for `queue_pcu`/`approaching_pcu`, the receiving
lane for the two receiving terms.

**Coverage.** Each lane is sampled every 2 m; a sample counts as covered if
some camera sees it inside the frame, below the horizon, at ≤ 0.6 m/pixel.
Coverage is measured from the stop line upstream, because that is where the
controller's quantities live.

**Two cameras, one vehicle.** Where cameras overlap, ground tracks within
3 m of each other on the same lane are merged before counting. Tracks
younger than 0.6 s are not counted (most ghost detections die sooner).

**Clutter.** A learned per-camera map (2 m cells) marks places where
"vehicles" sit for over 60 s without ever having driven in, and forgets
them over ten minutes. Stopped tracks in a learned clutter cell are not
queue. This, with the `moved_m` rule, took the queue bias caused by
detector hotspots from +0.42 to +0.09 PCU per link in the medium test.

**Queue past the edge of view (build guide §3.2.3).** When the back of the
queue reaches the end of coverage, `queue_truncated` is set and the hidden
part is extrapolated from the queue's growth rate over the 20 s before it
left the view — the back-of-queue shockwave speed, as in
Lighthill–Whitham–Richards — capped by lane length. The hidden growth
decays (time constant 30 s) instead of running on linearly: a queue that
has just spilled out of view is still growing, one that has been out of view
for two minutes has usually met the next green. Linear growth overshot by
+12 PCU per truncated tick on the worst held-out seed; the time constant was
chosen on a TRAIN seed (truncated-tick error 0.081 → 0.067 PCU). The
truncation factor starts at 0.95 and decays to 0.7 over 180 s, so a long
outage slides the controller down its own ladder instead of trusting a
guess forever.

**Where the view really ends — built, measured, and switched off.**
Geometric coverage says how far a camera *could* see; in dense traffic the
tail of a queue disappears behind the vehicles in front of it long before
that (seen to ~77 m on a lane covered to 98 m). The estimator can learn each
lane's **occlusion horizon** — the 0.9 quantile of the queue backs it has
actually observed — and treat a queue reaching that far as truncated. It
does what it was built to do to the bias: on the two TRAIN seeds at heavy
demand it went from −0.55 to −0.36 and from −0.17 to −0.03 PCU per link
(mean error 0.759 → 0.747 and 0.369 → 0.393: less biased, no more
accurate). And it makes the controller worse: CC-A-CAMP on those cameras
had **21.8 %** and **14.7 %** more person-delay on the same two seeds. Extrapolating every queue that reaches
a learned, shorter horizon trades a steady under-count for noisy
over-counts on exactly the approaches the controller is choosing between,
and a pressure controller minds the second more. It ships switched off
(`horizon_quantile=0`), with its test, for a controller that can use it.
A less biased estimate is not automatically a better input: the closed
loop is the judge.

**Confidence** = coverage × camera health × visibility × truncation ×
(0.9 + 0.1 × receiving-lane coverage), each factor in [0, 1] and each
reported separately in the event. Coverage compares the metres seen from the
stop line with what the controller needs (`EstimatorConfig`: 60 m of
approach and 30 m of receiving lane). Visibility is
1 − 0.3 × an exponential average (τ 30 s) of the share of vehicles in the
lane that the tracker is coasting rather than seeing — counting only
vehicles that are inside the frame and have actually driven. The first
version counted every track, and the closed loop exposed it: vehicles
coasted past the frame edge and flickering hotspot false positives made
fully visible lanes read "25 % unseen", and the controller dropped to
fixed-time on 5–8 % of junction-ticks for no physical reason (junction
minimum confidence below 0.8 on 20 % of ticks; 1.1 % after the fix, same
run). The weights are set so that a healthy, well-covered camera sits above
the ladder's 0.8 line.

### 3.7 Phase-aware incident rules

Each rule reads ground tracks plus the live signal state
(`SignalChanged`) and produces a per-link score in [0, 1] with evidence:

| Rule | Fires when | Why the guard |
|---|---|---|
| `stuck_on_green` | the lead stopped vehicle in a lane, clear road ahead, stays stopped through protected green while a *sibling* lane on the same green discharges (15 s), or 45 s with no sibling to compare against; receiving lane not full | on red the same stop is a lawful queue; a permissive `g` movement waiting for a gap is doing its job; a full exit is congestion, not an incident |
| `midblock_stop` | a vehicle that *drove in* (≥ 5 m of travel) stays stopped with ≥ 25 m of empty lane ahead, clear of the stop-line queue: 15 s if vehicles queue behind it, else 30 s (90 s for buses and autos, which stop to board) | a vehicle that never moved is a detector hotspot on a billboard |
| `wrong_way` | a track travels ≥ 15 m over ≥ 3 s against its lane's direction | keyed to the track, not the place, so it persists as the vehicle moves |
| `collision_cue` | two vehicles that were ≥ 4 m apart converge until footprints overlap, then both stay stopped ≥ 10 s, one having moved at ≥ 5 m/s just before | ByteTrack can briefly hold two tracks on one vehicle; those overlap from birth |
| `flow_void` | a stretch ≥ 60 m from the stop line that normally carries ≥ 30 % of the approach's traffic sees nothing for 90 s while neighbours keep flowing *and* ≥ 3 vehicles are seen leaving this lane slowly just upstream of it | finds obstructions no detector class covers — debris, a pothole, a fallen tree — by the traffic swerving round them; SUMO and real drivers alike leave turn lanes empty for minutes by choice, without swerving |

The first draft's `no_discharge` rule became `stuck_on_green`'s sibling
comparison: "the head did not move 8 s into green" fired on every slow
starter; "the head did not move while the lane next to it emptied" does not.

These thresholds are the hand-set defaults. The incident gate logs every
rule hit at deliberately low thresholds with the measure behind it, and
`scripts/m8_incident_analysis.py` chooses the operating point on TRAIN seeds
against a false-alarm budget, then scores held-out seeds once. The measured
points ship as `OPERATING_POINTS` (`VISION_RULES`, default `quiet`):
`quiet` (1 alarm/h budget) catches 19 % of in-view injected incidents at
1.7 false alarms per hour for the corridor; `assist` (10/h) added
`stuck_on_green`, which earned its place on the TRAIN seeds and caught
nothing more on held-out ones (19 % at 10.3/h); the hand-set defaults catch
37 % at 37/h. False alarms are counted as the engine raises them — again
after it clears and cools down; the first analysis counted one per place
per run and under-stated every rate. `collision_cue` fires on overlapping
footprints in dense queues and is off at both points.
The rules are a feature for M6's fusion layer, not a detector on their own.

**Measured as a fusion input** (`baselines/2026-09-27_m8_incident_fusion/`,
`scripts/m8_incident_fusion.py`). A logistic regression over three kinds of
feature was tested on held-out seeds:
- z-scores against each link's normal behaviour;
- contrast features (stopped on green, slower than its green siblings,
  queue never cleared);
- the rules' evidence.

What it found:
- **With M6's whole-lane SUMO features** (noise-free, an upper bound) it
  catches 37–43 % of in-view incidents on fresh seeds 6–10, including 9–11
  of 19 stalls, at 0.19–0.26 false alarms/h. The re-tuned rules catch 11 %.
  The post-hoc seeds 1–5 give 40–45 %.
  - These figures are after removing a SUMO artefact: an empty blocked lane
    reports its 0.1 m/s limit as its mean speed.
- **The normal baseline** is worth +29 to +30 points of that.
- **With the cameras alone** it did better than the rules: 28 % with 1 false
  alarm in 15 h, against 11 % with 26. But it failed the bar set in advance,
  because the recall gain's interval touched zero. It was not adopted.
- **The rule evidence** added to camera traffic features on seeds 6–10 (+15
  points), not in the first run on seeds 1–5, and hardly at all to lane
  sensors.

The link's `vision_score` is the maximum rule score, and goes straight into
`FusionLayer`'s existing `vision_score` feature. A persistence gate (score
≥ 0.5 for 3 s) turns sustained scores into `AnomalyUpdated(source=VISION)`
candidates — which still only become incidents through an operator
(ADR-006). There is no person rule.

**Fire and smoke (version 2 passed its bars but failed the street probe; not wired in).** No rule over
vehicle tracks can see a fire, so this is the one incident type with its own
detector.
- **The model:** a two-class YOLO11-S (fire, smoke), trained in Colab
  (`notebooks/m8_fire_smoke.ipynb`). It is trained on the public D-Fire
  dataset (21,527 images, CC0) plus Bengaluru traffic frames with no fire,
  because orange autos, red buses, brake lights, sodium lamps and dust are
  what fool a fire detector on Indian roads.
- **How it will run:**
  - once a second per camera, not at 5 fps;
  - its boxes are the evidence;
  - a detection must persist, like every other rule;
  - it then becomes an `AnomalyUpdated` candidate for an operator to
    confirm (ADR-006).
- **The alarm threshold** is chosen on the notebook's validation split, as
  the lowest one that keeps false alarms on its Bengaluru validation
  frames at or under 1 %.
- **The bar, set before training:**
  - at least 85 % of D-Fire's test images with fire or smoke raise an
    alarm;
  - at most 1 % of the 250 Bengaluru test frames do
    (`scripts/m8_fire_eval.py`). None of those frames shows a fire, and
    none was used to train or tune the model.
- **Version 1 failed both bars and is not adopted**
  (`baselines/2026-09-28_m8_fire_v1/`).
  - It alarmed on 12.8 % of the Bengaluru frames, on orange vehicles and
    signs and on hazy road.
  - It found 79 % of D-Fire's test fires.
  - Its training never got the Bengaluru frames: the notebook carried on
    without them. Version 2 downloads them itself from UVH-26 (never a
    test frame or test camera), and stops if it cannot.
- **Version 2 passes both bars** (`baselines/2026-09-28_m8_fire_v2/`).
  - It found 93 % of D-Fire's test fires and smoke.
  - It alarmed on 0.4 % of the Bengaluru frames: one orange container.
  - At its threshold (0.05) it also alarms on 28 % of D-Fire's no-fire
    images, yet it scores Bengaluru frames near zero. So it may have learned
    that a Bengaluru CCTV picture is never a fire.
  - `scripts/m8_fire_paste_probe.py` pasted D-Fire test flames into the
    Bengaluru frames and onto grey to check this. **It failed.** Fire was
    found about half as often in the street at 128 px (0.48 against 0.94),
    and at 256 px 0.67 against 0.92. The bar, set before the run, was a
    ratio of at least 0.8. So the detector is not wired in. It needs street
    fires in its training.
- **Not yet measured:**
  - fire in Indian junction footage, of which there is none labelled;
  - the persistence settings, which need video.

### 3.8 Camera health, including calibration drift

Per frame: sharpness (variance of the Laplacian against the camera's own
baseline), exposure (mean), contrast (against the camera's own baseline —
an empty grey car park is flat and healthy; an absolute threshold flagged
474 of 597 frames of a real clip), frozen frames (repeated frame hash),
tamper or occlusion (a sudden collapse of edge density), frame rate. Per
minute, from the traffic itself: **calibration drift**. Moving vehicles
should travel along lane directions and stay on the road; if a camera is
bumped, projected tracks start heading across lanes and landing off the
carriageway. Mean heading error and off-road fraction over a sliding window
flag `CALIBRATION_DRIFT` without anyone looking at the camera.

**A camera that sees nothing on a road that has traffic.** Every pixel
check passes on a camera whose detector has quietly stopped finding
vehicles — the stock COCO model on an overhead view does exactly that. The
activity monitor learns how many vehicles normally drive into each camera's
view (a 15-minute average, which decays four times slower once the camera
has gone quiet, so a blind camera cannot talk itself into "a quiet road" in
minutes) and flags the camera when nothing has been seen for two minutes
where at least eight arrivals were expected — a silence a Poisson process
at that rate produces less than 0.04 % of the time. A camera that has seen
no vehicle at all ten minutes after start-up is flagged too. It does not
fire on a jam: a vehicle that drove in and is standing in view is traffic,
even when nothing new arrives, and it counts as one arrival however long
it stands.

A silent camera is `DEGRADED` and says why, for the operator. Only the
never-worked case reaches the controller (health 0.3, under the adapter's
hard-failure line). The first version sent every silent camera there, and
the heavy-demand closed loop showed the flaw: when the gates' demand ends
the roads really do empty, 2,300–2,700 s into a run, and every camera
"went blind" in turn — the junctions dropped to fixed-time for no reason
(1,359 junction-ticks in one run). One camera cannot tell a road that
emptied from a detector that stopped seeing; stop-bar detection can, and
that cross-check lives in the controller adapter, where both are known
(§3.10).

Status `OK`/`DEGRADED`/`FAILED` goes out as `CameraStatus` and multiplies
into every confidence that camera contributes to.

### 3.9 Privacy

- No frame is written anywhere in normal operation. A ring buffer holds the
  last few seconds in memory.
- When an incident candidate is raised, that buffer is **redacted** — every
  person box pixelated, every two-wheeler box pixelated whole (from a pole
  or an overhead view the rider sits in the middle of the box, not on top),
  and a plate strip of every vehicle pixelated — and only then stored,
  tagged with a retention period, to MinIO (already in
  `docker-compose.yml`, unused until now).
- Redaction uses what is **tracked**, not only what is detected in that
  frame: on real footage a cyclist the detector saw only below its
  confidence threshold was being tracked but not blurred.
- Track ids are per camera and restart with it, so there is no join key
  across cameras or days — pseudonymous by construction, as ARCH §21
  requires of any per-vehicle stream.
- Camera credentials stay out of files and logs: a registry `source` can
  name environment variables (`rtsp://${CAM_USER}:${CAM_PASS}@…`), and every
  log line and error shows the URL with its user-info masked.

### 3.10 Feeding the controller

`vision_service/sim/closed_loop.py`'s `VisionSensor` (the gates) and
`sim_service/control/vision_feed.py`'s `VisionFedStrategy` (the live
stack) are the adapters between the estimator and a signal strategy. Both
use `itms_domain.camera`, so they cannot drift apart. They swap the four
`QueueSample` fields in the controller's `JunctionContext` for the camera
estimate and decide what, if anything, the controller hears about
confidence:

| mode | confidence passed on | what the ladder does |
|---|---|---|
| `trust` | none | always full adaptive control |
| `honest` | every value | the middle rung whenever a link reads below 0.8; the bottom rung below 0.5 |
| `failsafe` (default) | only values below 0.5 — a camera offline or failed, a lane nobody sees, a camera caught blind | full adaptive control until a camera really fails |

**The ladder's middle rung, fixed.** A-CA-MP's ladder is full control at
0.8 and above, a blend between 0.5 and 0.8, and fixed-time below 0.5. The
blend mixes the live estimate with the junction's demand memory. With no
memory configured (every M5 and M8 arm, and `make dev`), the first version
did not blend; it dropped to `fixed_time.propose`, M2's demand-blind
cycler, which ends any green older than its 7 s minimum on the tick it is
entered. A camera estimate at 0.7 confidence is far better input than that,
and dropping into the cycler for a tick or two at a time truncated greens.
Measured before the fix (5 held-out seeds, paired):

- stock COCO detector, medium demand: `honest` spent 44 % of junction-ticks
  in the cycler and cost **+28 %** person-delay against the controller on
  truth; `failsafe` with the same detector cost **+5 %**;
- in-domain detector: `honest` +8 % against `trust` at medium (4/5 seeds
  worse) and +10 % at heavy (3/5), from sub-0.8 values on about 1 % of
  junction-ticks.

A blend with no history to blend toward is the live reading — that is
`memory.blend`'s own definition — so the middle rung without a memory now
controls on the live estimate (`acamp.py`; the cycler is kept behind
`use_memory_blend=False` for M5's sensor-degradation experiment). `honest`
and `failsafe` then make the same decisions except when the blend has a
memory to lean on. M5's own finding pointed the same way: history helps
where live data is absent, not where it is merely noisy.

**A camera that went blind** — frames arriving, the detector no longer
finding vehicles — reads as an empty road at full confidence, and no check
inside the vision service can tell that from a road that emptied (§3.8).
The controller can, because it also has a stop-bar loop.
`itms_domain.camera.BlindCameraCheck` compares, per link, the loop over the
last 20 m before the stop line (a zone every planned camera sees) with what
the camera reports. A stretch in which the loop keeps seeing vehicles and
the camera sees none makes the link a hard failure until the camera sees
one again. Evidence is counted in seconds the loop is occupied while the
camera tracks no vehicle anywhere on that approach. 30 s of it is
blindness. The evidence is wiped when the camera sees a vehicle, or when
the loop has been empty for 10 s.

A caught link stays failed until the camera sees a vehicle on it (the
first version released it whenever the loop went quiet, and a blinded
junction flickered in and out of fixed-time). It took three versions to
get the evidence right, each measured on TRAIN seeds
(`scripts/m8_blind_check_calibration.py`: 8 fault-free runs and 2 with the
busiest junction's detector blinded for half an hour):

| version | false alarms / h, corridor | blinded links caught |
|---|---:|---|
| `has_demand` (a vehicle anywhere on a lane up to 600 m long), 60 s hold | 34 | 32 / 32 |
| stop-bar loop, but "seen" = queue + approaching > 0.1 PCU, 30 s of loop time | 10.5 | 32 / 32 |
| stop-bar loop, "seen" = any tracked vehicle on the approach, 30 s of loop time | **1.6** | **32 / 32**, median 85 s |

The second version's "seen" missed a car creeping over the loop (neither
stopped nor due within 8 s) and a car the tracker put in the next lane. The
link-state event now carries `vehicles_seen`, the vehicles tracked on the
link's whole approach, for exactly this. The remaining false alarms all
came with the stock detector, in two of its four runs (27 s and 47 s of a
junction flagged); with the in-domain detector there were none.

Measured on held-out seeds (`baselines/2026-09-25_m8_ladder_blindcheck/`):

- **the ladder fix removes the confidence penalty**: `honest` now makes the
  same decisions as `failsafe` on every seed, at both demand levels and
  with both detectors (the stock detector's `honest` was +21.4 % against
  `failsafe`). In M5's own experiment (confidence held at 0.6 everywhere)
  the live rung beats the old fixed-time one by 34 % at light demand
  (significant) and 14 % at medium (4/5 seeds);
- **a real failure** — all four cameras of the busiest junction dark for 30
  minutes: trusting them costs **+12.6 %** (significant); `failsafe`
  recovers about half of it (−5.3 % against `trust` in the same outage, 4/5
  seeds lower, not significant at n = 5);
- **a blind one** — the same cameras sending frames with nothing detected:
  believed, it costs exactly what the dark one does (+12.6 %), and without
  the cross-check `failsafe` never notices. With it the junction spends as
  long in fixed-time as the known outage does (6.9 % of junction-ticks
  against 7.0 %), and a third of the cost is recovered (−4.0 %, 4/5 seeds,
  not significant). Most likely the rest is the time the check needs to be
  sure (a median 85 s on TRAIN seeds), but at n = 5 the blind run with the
  check and the known outage cannot be told apart (+1.4 %, not
  significant);
- **what the cross-check costs when nothing is wrong**: with the in-domain
  detector, one brief false alarm on one held-out seed per level (4 and 8
  junction-ticks of fixed-time); means +1.1 % at medium, +3.8 % at heavy,
  neither significant — the heavy figure is one seed that moved 20 % on
  those 8 ticks, the kind of swing heavy runs make on any small nudge. With
  the stock detector at medium it also fired on two seeds (5 and 1
  junction-ticks), which moved those runs by 0.0 % and +0.2 %.

Below 0.5 the estimates are not usable, and the bottom rung is what the
ladder is for. The raw confidence is still published on
`vision.link-state` for anything that can use it better — a controller
with a working demand memory, or the dashboard.

What stays ground truth in these runs, stated rather than hidden:
`has_demand` and `wait_times_s`, the safety kernel's max-wait inputs,
which in a deployment come from stop-bar presence detection.

**Live.** The same swap runs in the live stack:
`sim_service/control/vision_feed.py` consumes `vision.link-state` into a
thread-safe latest-value table, and `CONTROL_SENSOR=vision` wraps every
junction's A-CA-MP in `VisionFedStrategy` (`VISION_CONFIDENCE`, default
`failsafe`). A link whose last estimate is older than 3 s — the vision
service stopped, the bus lagged — or that was never reported reads
confidence 0, a hard failure, so the ladder falls back instead of acting on
state from a minute ago. Age is judged from the envelope's `occurred_at`, so
a consumer group replaying an old stream on start-up is not mistaken for
the present; a message older than the one already held is ignored.

---

## 4. SimCam, the digital-twin camera

SimCam takes a snapshot of every vehicle (position, heading, length, width,
class) from TraCI — or from the `VehiclePositionUpdated` stream, which is how
it runs live under `make dev` — and films it through a camera:

1. Each vehicle is a class-sized cuboid; its eight corners project to a
   bounding box.
2. **Occlusion**: boxes are sorted by distance to the camera and each one's
   visible fraction is what is left after the boxes in front of it are
   subtracted (a coarse per-box grid, vectorised).
3. **Detection errors** come from a `PerceptionErrorModel`:
   - recall by class, times a visibility curve and a size curve (small,
     distant objects are missed);
   - **bursty misses** — each object carries a two-state Markov chain, because
     real misses persist while a vehicle is behind a bus or in glare, and
     independent per-frame misses would flatter the tracker;
   - class confusion (auto-rickshaw ↔ car, motorcycle ↔ bicycle), *sticky*
     per object — a detector that calls one auto a car tends to keep doing
     so;
   - box jitter proportional to box size;
   - false positives: short-lived ghosts spread over the road area, plus a
     few **persistent hotspots** per camera placed just off each lane (a
     billboard, a parked auto, a shadow) that fire frame after frame — the
     realistic failure that stationary-object logic has to survive.

   Presets: `ideal`, `finetuned_day` (an in-domain model, e.g. YOLO11
   fine-tuned on BMD-45), `coco_pretrained` (the domain gap the BMD-45 paper
   measures — UA-DETRAC-trained models at 33.6% mAP on Indian CCTV against
   83.8% in-domain), and `night_rain`. These presets are **assumptions to be
   replaced by measurement** once real annotated footage is run through
   `vision_service/eval/mot.py`; the experiments sweep across them for
   exactly that reason. The first measurement (Bengaluru CCTV,
   `baselines/2026-09-25_m8_uvh26_detector/`) says both are optimistic
   about two-wheelers and autos: a real in-domain model finds 0.66 and 0.75
   of them against `finetuned_day`'s 0.92 and 0.94, and a real stock model
   finds one two-wheeler in eight and recognises no auto. For cars the
   twin's measured recall is close to the real one (0.89 and 0.76 against
   0.84 and 0.72).

   Three presets are now **fitted to those measurements**
   (`scripts/m8_simcam_calibrate.py`, maximum likelihood on every labelled
   box's size and outcome): `uvh26_640` and `uvh26_1280` (IISc's model at
   640 and 1280 px input) and `stock_640`. Each has a base recall and a size
   curve per vehicle type (`size_h50_by_class`), and confusions as
   measured. Bursts, false positives and person recall stay as in the
   preset each starts from, because a still image cannot measure them. The
   size curve was the assumption furthest off: `finetuned_day` halved its
   recall at a 14 px box, while the real model at 640 px halves it at 53 px
   for a car. A car about 35 px tall, at the edge of a planned camera's
   coverage, is found about 19 % of the time at 640 px input and 55 % at
   1280. On held-out seeds the controller on `uvh26_1280` costs +2.3 %
   against perfect data at medium, as the assumed detector did (+1.7 %),
   and +8.0 % at heavy, where the assumed detector cost +17.3 % (the
   difference is not significant); on `uvh26_640` +9.3 % and +16.8 %; on
   `stock_640` +17.2 % at medium, three times the old assumption's +5.5 %
   (`baselines/2026-09-26_m8_measured_detectors/`).

   Two more presets, `itms6_640` and `itms6_960`, are fitted to the
   adopted fine-tune (`baselines/2026-09-27_m8_finetune_v2/`). At 640 px
   it halves recall at a 42.5 px car rather than 53 px.
   - **Medium demand:** the controller on `itms6_640` costs +4.7 %
     (significant, 0/5 seeds lower), about half what IISc's model cost at
     640 px (+9.3 %). The direct comparison between the two (−4.2 %) is
     not significant. It is within 2.4 % (n.s.) of IISc's model at
     1280 px, which needs about five times the CPU.
   - **Heavy demand:** both fine-tune presets had one run each go into a
     long jam, which pulled their means to +17–18 % (n.s.). Their medians
     matched IISc's model at 1280 px. Runs on perfect data never jammed,
     so these jams come from the camera path; they were not traced.
4. Positions are interpolated between SUMO steps, so the vision pipeline runs
   at 5 fps while the simulation and the controller keep their 1 Hz tick.

SimCam can also rasterise a frame (road, lane markings, vehicles) for demo
video and for exercising the pixel-level health checks. The detection path
does not depend on that rendering.

---

## 5. Events

| Event | Topic | What |
|---|---|---|
| `LinkStateEstimated` (new) | `vision.link-state` | per link: the four `QueueSample` quantities, confidence and its factors, coverage, truncation, `vision_score`, contributing cameras |
| `CameraStatus` (new) | `vision.camera-status` | per camera: status, health score, sharpness, brightness, fps, drift metrics |
| `AnomalyUpdated` (existing, `source=VISION`) | `anomaly.updated` | vision-raised candidates |

`ApproachState` is deliberately left alone: the web app reads it per edge from
the SUMO adapter, and changing its key would break that consumer.
`LinkStateEstimated` is the movement-level estimate its own `doc` field
anticipates, published beside it.

---

## 6. How it is evaluated

| Experiment | Script | Question |
|---|---|---|
| Perception gate | `scripts/m8_perception_gate.py` | Per link, how far are camera estimates from SUMO truth, by preset and demand? Detection recall/precision, tracking identity, speed error, coverage, truncation. |
| Closed loop | `scripts/m8_closed_loop_gate.py` | CC-A-CAMP on camera-derived state vs on truth vs Webster, paired held-out seeds. How much of the win over Webster survives realistic cameras — and does the confidence ladder help or hurt? |
| Incident gate | `scripts/m8_incident_gate.py` | Using M6's own injector (stalled vehicles, blocked lanes): recall, detection time, false alarms per hour, localisation — the same table M6's graph detector reports. |
| Camera outage | `m8_closed_loop_gate.py`, `...:outage` arms | Four cameras at the busiest junction dark for 30 min: what does trusting them cost, and does confidence recover it? |
| Calibration drift | unit + scripted | Does a 3° bump get flagged, and how fast? |
| Real footage | `scripts/m8_real_video_smoke.py` | A real YOLO11 on real video: speed, ONNX parity with our own decoder, track fragmentation, stationary objects, camera-health false alarms and fault detection on real pixels, redaction. A smoke test, not an accuracy number. |

Tracking is scored the MOTChallenge way: CLEAR-MOT keeps a truth–track pair
from one frame to the next while it still overlaps (so an identity switch is
a switch the tracker made, not a re-shuffle of the per-frame assignment),
and a box on a vehicle too hidden to be scored is neither a hit nor a false
positive.

What SimCam cannot tell you: how a real detector performs on Vijayawada
footage. That number comes only from annotated real video, and the MOT
evaluator is there for it. Until then, every closed-loop number carries the
preset it was measured under.

---

## 7. Failure modes considered

| Failure | Effect | Handling |
|---|---|---|
| Queue longer than the view | `queue_pcu` under-counted | truncation flag, shockwave extrapolation, decaying confidence |
| Bus occludes lanes behind it | missed vehicles | second-stage ByteTrack association, visibility term in confidence |
| Night, rain, glare | recall drops | health score multiplies confidence; controller falls down its ladder |
| Camera bumped | tracks land in wrong lanes | calibration-drift detector from traffic headings |
| Frozen or looping feed | stale state looks valid | frozen-frame detector → `FAILED`, confidence 0 |
| Camera offline | no data | confidence 0 — never "zero vehicles" |
| Lane-free driving | per-lane split noisy | approach-level totals; per-lane error reported separately |
| Two-wheeler swarms | boxes merge | class-aware NMS thresholds; PCU of a missed motorcycle is 0.3, so the pressure error is bounded |
| Auto-rickshaw not in COCO | wrong PCU | fine-tune path (BMD-45); `coco_pretrained` preset quantifies the cost |
| Person in frame | privacy | detected only to blur; no person rule |
| Detector hotspot on street furniture | a "vehicle" stopped forever, phantom queue | `moved_m` (never drove in → furniture), learned clutter map, `midblock_stop` requires arrival |
| Stock COCO model on an overhead view | vehicles missed almost entirely (road paint comes out as "airplane", which the class map drops); the camera reports an empty road with full confidence | measured on a real overhead clip (M8 results: 2–3 vehicle boxes across 43 frames that contain vehicles, for YOLO11 n/s/m): overhead cameras need fine-tuned weights. The activity monitor (§3.8) now marks such a camera `DEGRADED` for the operator once it has learned the traffic it should be seeing; one that has seen no vehicle at all ten minutes after start-up is also a hard failure for the controller. A camera that sees a few vehicles where it should see many still passes |
| Camera back after an outage | old tracks re-attached to new vehicles; stale stop times | tracking resets after any gap longer than the tracker buffer (§3.4) |
| Detector slower than the cameras | a backlog of stale frames | video mode keeps only the newest frame per camera, stamped with its capture time; cameras are served oldest-first so none starves |
| Vision service stops or lags | the controller acts on old state | the live feed reads anything older than 3 s as confidence 0 (§3.10) |
| Camera blind: frames arrive, the detector finds nothing | an empty road at full confidence; every health check passes | the controller's stop-bar cross-check (§3.10): 30 s of loop time with nothing tracked on the approach makes the link a hard failure until the camera sees a vehicle |

---

## 8. Deliberately out of scope for this build

- Training or fine-tuning YOLO11 on BMD-45 (needs a GPU and the dataset; the
  adapters, class maps and evaluator are ready for the result). IISc's own
  UVH-26-trained YOLO11-S has been measured instead, and a corrected
  fine-tune of it on UVH-26 is ready to run in Colab (§3.2). Fine-tuning on local footage is
  for when Vijayawada footage shows the model falls short there.
- Multi-camera re-identification across junctions (would create exactly the
  cross-camera join key ARCH §21 forbids).
- Fully automatic calibration. Lane-mark calibration (`itms_geo.lanecal`)
  needs a person to click the marks once; recovering the scale from the
  camera alone (the pinhole route) turned out to be ill-conditioned for
  cameras that look down the road, so it is kept as a cross-check only.

---

## 9. What changed between the design and the build

| Draft | Built | Why |
|---|---|---|
| coverage at ≤ 0.35 m/px | ≤ 0.6 m/px | 0.35 would stop a planned camera's view near 85 m; a car at the 0.6 limit is still ~30 px |
| stopped: 1.0 m/s, 2 s hysteresis | stop below 0.8 m/s held 1 s, move above 2.0 m/s | separate stop and move thresholds keep speed jitter near 1 m/s from flickering the state; tuned against SimCam truth |
| every box measured | border boxes predicted; velocity seeded from two clean fixes | both produced phantom slowdowns and phantom queue heads |
| `stalled_on_green` (6 s into green, 20 s) and `no_discharge` | `stuck_on_green` with a sibling-lane comparison | fixed thresholds fired on slow starters and permissive movements |
| `flow_void` at 30 s | 90 s, ≥ 60 m from the stop line, share ≥ 30 %, and swerving | at 30 s it fired on every empty turn lane |
| thresholds set by hand | logged at low thresholds, chosen on TRAIN seeds | one set of runs gives the whole recall / false-alarm curve |
| error model without persistent false positives | per-camera hotspots | the stationary-object logic needed something real to beat |
| calibration by surveyed points only | plus lane-mark calibration | a survey is the expensive part of a camera install |
| visibility over every track | over in-frame vehicles that drove in | frame-edge coasting and hotspot ghosts dragged confidence under 0.8 on 20 % of junction-ticks; found by the closed-loop gate, fixed, and the affected arm re-run |
| confidence straight into the ladder | `failsafe` adapter: only hard failures | the ladder's no-memory middle rung truncates greens; see §3.10 |
| lane health = worst camera that sees it | coverage from the cameras still working | one dead camera zeroed lanes a neighbour's camera covered in full |
| a re-acquired stopped vehicle starts fresh | stitched to the track it lost (≤ 10 s, ≤ 3 m) | a stalled car re-found with `moved_m = 0` looks like furniture to every rule (found tracing a missed incident) |
| absolute contrast floor | contrast against the camera's own baseline | a grey car park is flat and fine (474 false alarms in 597 real frames) |
| stitched stop applied at once | applied once the re-found track is confirmed slow | a creeping vehicle was counted as queued (medium queue error 0.051 → 0.063) |
| tracks carried across gaps in the video | reset after any gap longer than the tracker buffer | ByteTrack's frame-counted buffer re-attached pre-outage tracks after a 30-min blackout |
| hidden queue growth linear | decaying, τ 30 s | +12 PCU overshoot per truncated tick on the worst seed |
| view ends where geometry says | a learned per-lane occlusion horizon was built, and ships **off** | it cut the heavy-demand under-count and cost the controller +15–22 % person-delay on the TRAIN seeds (§3.6) |
| collision cue across any two tracks | only tracks from the same camera | two cameras' tracks of one vehicle "converge" by construction |
| ByteTrack could hold a tracked and a lost copy of one vehicle | the younger duplicate is dropped (IoU ≥ 0.85) | duplicates inflated counts and fed the collision cue |
| no check that a camera still sees traffic | activity monitor (§3.8) | the overhead-camera failure above |
| a silent camera is a failed camera | silent → reported; only never-worked → hard failure | roads emptied at the end of each gate run and the controller fell back to fixed-time |
| operating points scored with one alarm per place per run | replay mirrors the engine's raise / clear / cooldown | the old replay under-counted false alarms (hand-set defaults: 32 → 37 per hour) |
| CLEAR-MOT by a fresh optimal assignment every frame | last frame's pairs kept while they still overlap, as the metric defines | two tracks side by side traded places on hair's-breadth IoU differences, each trade counted as an identity switch |
| every tracker box scored | boxes on vehicles too hidden to score are left out, not charged (MOT17's distractor rule) | the second ByteTrack stage, which keeps half-hidden vehicles tracked, was counted against the tracker |
| the ladder's middle rung, with no demand memory, fell to the min-green cycler | it controls on the live estimate (`acamp.py`) | confidence between 0.5 and 0.8 cut greens: +8 to +21 % person-delay for passing it on |
| no way to tell a blind camera from an empty road | stop-bar cross-check in the controller adapters, `vehicles_seen` on the event | a blind camera cost what a dark one does and nothing noticed |
| video mode: a shared frame queue that dropped the newest frame when full | the newest frame per camera, stamped at capture | a slow detector worked through stale frames and stamped them with its own clock |
| RTSP credentials in the registry and in logs | `${VAR}` in the source URL; user-info masked in every log line | a camera password in a config file and a log is a leaked password |
| the best single class against the threshold | scores summed per ITMS class before threshold and NMS | UVH-26's model spreads a car over five types; three in ten of the cars it found were dropped |
| free-text labels matched as far as "SUV" | every BMD-45 / UVH-26 label mapped, with a test | "MUV" matched nothing, so a model trained on either would never have counted one |
| detector presets assumed | three fitted to measured detectors, with a size curve per vehicle type | the assumed size curve credited a 640 px detector with far vehicles it misses; the controller's cost of a stock detector was a third of the measured one |

