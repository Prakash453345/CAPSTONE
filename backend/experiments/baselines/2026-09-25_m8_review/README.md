# Baseline — M8 vision, after a review for bugs and logic errors (2026-09-24/25)

Supersedes `baselines/2026-09-23_m8_vision/` for every gate. The code was
reviewed module by module; each defect found was fixed with a test, the
remaining next steps from the first baseline were built, and then **every
gate was re-run on the final code** (the first attempts at this re-run were
abandoned whenever a later fix touched what they measured — kept in
`superseded/` where they show something). Tables are printed by
`scripts/m8_report.py` from the JSON files here.

## Setup

As the first baseline: CC-A-CAMP exactly as `baselines/2026-09-18_gap_out/`,
19 planned cameras (`scenarios/networks/vijayawada/cameras.json`), SimCam at
5 fps, held-out `EVAL_SEEDS` 1–5 (incidents: TRAIN 101–102 to choose, EVAL
1–3 to score), 2 vCPU (`environment.txt`). Webster and truth runs contain no
vision code and are carried over from the first baseline (the perception
gate's truth-driven traffic reproduces the first baseline's exactly).
The detector presets are assumptions, not measurements of a real detector.

## What changed in the code

Defects (each with a regression test that fails on the old code):

| defect | how it showed | fix |
|---|---|---|
| `occurred_at` decodes to a `datetime`; the vision service divided it by 1000 | the live end-to-end run: the vision service died on its first message, and sim-service's camera feed swallowed the same error on every message, so the controller ran on confidence 0 throughout | `itms_common.events.occurred_at_s`; tests through the real Avro encoding |
| tracks survived a gap in the video | ByteTrack counts its buffer in frames: after a 30-min outage, a car queued on the same spot inherited a stop that began before it | tracking resets after any gap longer than the tracker buffer |
| a silent camera was a failed camera | heavy closed loop, `failsafe`: the gates' demand ends, roads empty, and every camera "went blind" in turn — 1,359 junction-ticks of fixed-time in one run | a learned-rate silence is reported to the operator only; a camera that has never seen a vehicle is still a hard failure |
| a long-standing vehicle counted as a second arrival | review | the activity monitor forgets only vehicles no longer in view |
| incident false alarms counted once per place per run | review of the analysis replay | the replay mirrors the engine's raise / clear / cooldown; the hand-set rules' rate goes from 32 to 37 per hour |
| "drove in" needed 5 m at ≥ 1.5 m/s | review of missed incidents | net progress of 5 m, however slow, counts too (`displaced_m`) |
| CLEAR-MOT re-assigned from scratch every frame | review | last frame's pairs are kept while they still overlap (0–2.5 % of the switches counted were artefacts) |
| boxes on too-hidden-to-score vehicles scored as false positives | review; `ideal` detection precision read 0.93 with no false positive in the model | MOT17's distractor rule; `ideal` precision now 1.00 |
| video mode kept stale frames and stamped them with processing time | review | newest frame per camera, stamped at capture; files replay at their own speed |
| RTSP passwords in logs; registry had to hold them | review | user-info masked everywhere; `${VAR}` in the source URL |
| calibration accepted 4-point fits (always exact) | review | at least 6 agreeing points required |
| a RESOLVED anomaly carried the resolution time as its start | review | the start time is kept per anomaly |
| the error model kept every vehicle it ever saw | review | state of vehicles gone 10 minutes is dropped |

Built from the first baseline's "next steps": stopped-track stitching that
waits for the re-found track to confirm the stop; the activity check in
camera health; **the live wiring** of `vision.link-state` into sim-service's
controller (`CONTROL_SENSOR=vision`, `failsafe` by default) with a live
end-to-end test; `failsafe` arms at every demand level.

## Decisions made on TRAIN seeds (`decisions.json`, `scripts/m8_estimator_ablation.py`)

**The occlusion horizon ships off.** It improves the estimate's bias and
worsens the controller:

| heavy, `finetuned_day`, seed | CC-A-CAMP on truth | on cameras, horizon off | on cameras, horizon 0.9 | horizon's effect |
|---|---:|---:|---:|---:|
| 101 | 638,597 | 460,109 | 560,550 | +21.8 % |
| 102 | 458,082 | 452,136 | 518,703 | +14.7 % |

(person-delay, `trust` mode; seed 101's run on truth is a heavy-demand
outlier — single heavy runs swing widely — which is why the comparison is
cameras against cameras). Estimate on the same seeds, queue MAE / bias
per link-tick: 101: 0.759 / −0.547 off → 0.747 / −0.362 on; 102: 0.369 /
−0.173 off → 0.393 / −0.029 on — less biased, no more accurate. `superseded/perception_gate_horizon_on.json`
is Gate 1 with it on.

**Stitching stays.** Queue MAE / bias per link-tick with it (current) and
without, `finetuned_day`, CC-A-CAMP on truth driving (these runs had the
horizon on; on the one medium seed checked it moved the error by 0.0025):

| level | TRAIN seed | stitching on | stitching off | horizon off |
|---|---|---|---|---|
| medium | 101 | 0.050 / +0.029 | 0.050 / +0.029 | -- |
| medium | 102 | 0.047 / +0.027 | 0.047 / +0.027 | -- |
| heavy | 101 | 0.747 / -0.362 | 0.747 / -0.364 | 0.759 / -0.547 |
| heavy | 102 | 0.393 / -0.029 | 0.390 / -0.033 | 0.369 / -0.173 |

On held-out seed 1 at medium (examined only to explain Gate 1, not to
choose), stitching costs 0.053 → 0.065
PCU: there it keeps more re-acquired vehicles out of the furniture filter
and the count rises above the truth. ByteTrack's duplicate removal changes
nothing measurable (0.065).

## Live end to end (`scripts/m8_live_e2e.sh`, `live_e2e/`)

sim-service in SUMO mode with `CONTROL_SENSOR=vision`, the vision service in
SimCam mode, a throwaway Redis; 300 simulated seconds at real time. See
`live_e2e/summary.txt`: 2,170 `vision.link-state` messages published and
consumed as they arrived (2,149 by the feed's last log line, a second
before the end), 0 % of 1,603 junction-ticks with a link in hard failure,
19 camera-status events, zero interlock violations, no error in either log.
No vision incident candidate in those five minutes under the `quiet` rules.
The first run of this test is how the `occurred_at` crash was found.

## Gate 1 — estimates vs SUMO truth (`perception_gate.json`)

| level | preset | queue PCU MAE / bias / corr | approaching MAE | recv. occupancy MAE | MOTA | IDF1 | det. recall car / 2W / auto | speed MAE (m/s) | lane acc. | confidence mean (<0.8) | queue truncated | candidates / h (no incident) |
|---|---|---|---|---|---:|---:|---|---:|---:|---|---:|---:|
| medium | `ideal` | 0.05 / +0.03 / 0.83 | 0.06 | 0.010 | 0.85 | 0.86 | 1.00 / 1.00 / 1.00 | 0.36 | 0.97 | 0.93 (0%) | 0.0% | 2.4 |
| medium | `finetuned_day` | 0.06 / +0.03 / 0.78 | 0.07 | 0.010 | 0.63 | 0.72 | 0.89 / 0.84 / 0.86 | 0.58 | 0.96 | 0.90 (0%) | 0.1% | 7.2 |
| medium | `coco_pretrained` | 0.08 / +0.03 / 0.78 | 0.11 | 0.010 | 0.23 | 0.53 | 0.76 / 0.68 / 0.71 | 0.92 | 0.94 | 0.86 (10%) | 0.1% | 14.4 |
| medium | `night_rain` | 0.08 / -0.03 / 0.70 | 0.11 | 0.010 | 0.05 | 0.40 | 0.57 / 0.54 / 0.57 | 1.45 | 0.94 | 0.82 (46%) | 0.1% | 12.0 |
| heavy | `ideal` | 0.30 / +0.06 / 0.93 | 0.11 | 0.019 | 0.91 | 0.90 | 1.00 / 1.00 / 1.00 | 0.27 | 0.98 | 0.93 (0%) | 1.0% | 96.0 |
| heavy | `finetuned_day` | 0.30 / -0.10 / 0.92 | 0.13 | 0.019 | 0.75 | 0.79 | 0.88 / 0.82 / 0.86 | 0.46 | 0.98 | 0.90 (0%) | 0.6% | 86.4 |
| heavy | `coco_pretrained` | 0.55 / -0.33 / 0.85 | 0.20 | 0.019 | 0.51 | 0.63 | 0.76 / 0.65 / 0.71 | 0.73 | 0.97 | 0.86 (6%) | 0.1% | 117.6 |
| heavy | `night_rain` | 0.86 / -0.73 / 0.72 | 0.22 | 0.018 | 0.33 | 0.48 | 0.56 / 0.51 / 0.56 | 1.05 | 0.96 | 0.82 (47%) | 0.1% | 108.0 |

Against the first baseline: heavy `ideal` 0.40 → **0.30** PCU (bias +0.17 →
+0.06, corr 0.81 → 0.93; the first baseline's whole bias there came from
over-shooting truncated queues, which the decaying hidden-queue growth
addresses), medium `finetuned_day` 0.051 → **0.062** (corr 0.83 → 0.78;
mostly stitching, see above); every other queue MAE within 0.005. MOTA/IDF1
move by at most 0.02 under the corrected scoring (`decisions.json`,
`tracking_metric_fix`: up to 2.5 % of counted ID switches were artefacts).
Candidates/h are the hand-set rules with no incident injected: up at medium
and for the weak presets at heavy (slow arrivals now count as "drove in";
`stuck_on_green` and `midblock_stop`), down for `ideal` and `finetuned_day`
at heavy (fewer collision cues).

## Gates 2 and 3 — the controller on cameras, and a camera outage (`closed_loop.json`)

**medium** (paired held-out seeds)

| arm | n | person-delay | p95 wait (s) | stops/veh | interlock viol. | confidence fed (mean) | fixed-time fallback |
|---|---:|---:|---:|---:|---:|---:|---:|
| `webster` | 5 | 106,912 | 83.8 | 2.24 | 0 | -- | -- |
| `truth` | 5 | 73,355 | 59.4 | 1.75 | 0 | -- | -- |
| `vision:finetuned_day:trust` | 5 | 73,789 | 61.2 | 1.71 | 0 | 0.90 | 0.0% of ticks |
| `vision:finetuned_day:failsafe` | 5 | 73,789 | 61.2 | 1.71 | 0 | 0.90 | 0.0% of ticks |
| `vision:finetuned_day:honest` | 5 | 79,622 | 67.0 | 1.78 | 0 | 0.90 | 1.3% of ticks |
| `vision:coco_pretrained:failsafe` | 5 | 77,324 | 63.2 | 1.82 | 0 | 0.86 | 1.7% of ticks |
| `vision:coco_pretrained:honest` | 5 | 93,890 | 69.0 | 2.23 | 0 | 0.86 | 44.1% of ticks |
| `vision:finetuned_day:trust:outage` | 5 | 83,111 | 75.4 | 1.73 | 0 | 0.78 | 0.0% of ticks |
| `vision:finetuned_day:honest:outage` | 5 | 78,097 | 59.4 | 1.78 | 0 | 0.78 | 8.6% of ticks |
| `vision:finetuned_day:failsafe:outage` | 5 | 78,693 | 59.2 | 1.78 | 0 | 0.78 | 7.0% of ticks |

| head to head (second vs first) | person-delay | stops/veh |
|---|---|---|
| `vision:finetuned_day:honest` vs `vision:finetuned_day:trust` | +7.9% n.s., 1/5 seeds lower | +4.1% n.s., 1/5 seeds lower |
| `vision:finetuned_day:failsafe` vs `vision:finetuned_day:trust` | +0.0% n.s., 0/5 seeds lower | +0.0% n.s., 0/5 seeds lower |
| `vision:finetuned_day:honest` vs `vision:finetuned_day:failsafe` | +7.9% n.s., 1/5 seeds lower | +4.1% n.s., 1/5 seeds lower |
| `vision:coco_pretrained:honest` vs `vision:coco_pretrained:failsafe` | +21.4% **SIG**, 0/5 seeds lower | +22.5% **SIG**, 0/5 seeds lower |
| `vision:finetuned_day:trust:outage` vs `vision:finetuned_day:trust` | +12.6% **SIG**, 1/5 seeds lower | +0.8% n.s., 2/5 seeds lower |
| `vision:finetuned_day:honest:outage` vs `vision:finetuned_day:trust:outage` | -6.0% n.s., 4/5 seeds lower | +2.8% n.s., 0/5 seeds lower |
| `vision:finetuned_day:failsafe:outage` vs `vision:finetuned_day:trust:outage` | -5.3% n.s., 4/5 seeds lower | +3.2% n.s., 2/5 seeds lower |
| `vision:finetuned_day:failsafe:outage` vs `vision:finetuned_day:honest:outage` | +0.8% n.s., 2/5 seeds lower | +0.3% n.s., 3/5 seeds lower |

| comparison | person-delay | stops/veh |
|---|---|---|
| `truth_vs_webster` | -31.4% **SIG**, 5/5 seeds lower | -21.6% **SIG**, 5/5 seeds lower |
| `vision:coco_pretrained:failsafe_vs_truth` | +5.4% **SIG**, 0/5 seeds lower | +3.8% n.s., 0/5 seeds lower |
| `vision:coco_pretrained:failsafe_vs_webster` | -27.7% **SIG**, 5/5 seeds lower | -18.7% **SIG**, 5/5 seeds lower |
| `vision:coco_pretrained:honest_vs_truth` | +28.0% **SIG**, 0/5 seeds lower | +27.1% **SIG**, 0/5 seeds lower |
| `vision:coco_pretrained:honest_vs_webster` | -12.2% **SIG**, 5/5 seeds lower | -0.3% n.s., 2/5 seeds lower |
| `vision:finetuned_day:failsafe:outage_vs_truth` | +7.3% **SIG**, 0/5 seeds lower | +1.6% n.s., 2/5 seeds lower |
| `vision:finetuned_day:failsafe:outage_vs_webster` | -26.4% **SIG**, 5/5 seeds lower | -20.4% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:failsafe_vs_truth` | +0.6% n.s., 3/5 seeds lower | -2.3% n.s., 4/5 seeds lower |
| `vision:finetuned_day:failsafe_vs_webster` | -31.0% **SIG**, 5/5 seeds lower | -23.4% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:honest:outage_vs_truth` | +6.5% n.s., 2/5 seeds lower | +1.3% n.s., 2/5 seeds lower |
| `vision:finetuned_day:honest:outage_vs_webster` | -27.0% **SIG**, 5/5 seeds lower | -20.6% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:honest_vs_truth` | +8.5% **SIG**, 0/5 seeds lower | +1.7% n.s., 1/5 seeds lower |
| `vision:finetuned_day:honest_vs_webster` | -25.5% **SIG**, 5/5 seeds lower | -20.3% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:trust:outage_vs_truth` | +13.3% **SIG**, 0/5 seeds lower | -1.5% n.s., 4/5 seeds lower |
| `vision:finetuned_day:trust:outage_vs_webster` | -22.3% **SIG**, 5/5 seeds lower | -22.8% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:trust_vs_truth` | +0.6% n.s., 3/5 seeds lower | -2.3% n.s., 4/5 seeds lower |
| `vision:finetuned_day:trust_vs_webster` | -31.0% **SIG**, 5/5 seeds lower | -23.4% **SIG**, 5/5 seeds lower |

**heavy** (paired held-out seeds)

| arm | n | person-delay | p95 wait (s) | stops/veh | interlock viol. | confidence fed (mean) | fixed-time fallback |
|---|---:|---:|---:|---:|---:|---:|---:|
| `webster` | 5 | 648,447 | 427.0 | 3.23 | 0 | -- | -- |
| `truth` | 5 | 457,164 | 270.6 | 2.73 | 0 | -- | -- |
| `vision:finetuned_day:trust` | 5 | 516,839 | 352.2 | 3.01 | 0 | 0.90 | 0.0% of ticks |
| `vision:finetuned_day:failsafe` | 5 | 516,839 | 352.2 | 3.01 | 0 | 0.90 | 0.0% of ticks |
| `vision:finetuned_day:honest` | 5 | 569,482 | 418.4 | 3.26 | 0 | 0.90 | 1.2% of ticks |

| head to head (second vs first) | person-delay | stops/veh |
|---|---|---|
| `vision:finetuned_day:honest` vs `vision:finetuned_day:trust` | +10.2% n.s., 2/5 seeds lower | +8.5% n.s., 2/5 seeds lower |
| `vision:finetuned_day:failsafe` vs `vision:finetuned_day:trust` | +0.0% n.s., 0/5 seeds lower | +0.0% n.s., 0/5 seeds lower |
| `vision:finetuned_day:honest` vs `vision:finetuned_day:failsafe` | +10.2% n.s., 2/5 seeds lower | +8.5% n.s., 2/5 seeds lower |

| comparison | person-delay | stops/veh |
|---|---|---|
| `truth_vs_webster` | -29.5% **SIG**, 5/5 seeds lower | -15.5% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:failsafe_vs_truth` | +13.1% n.s., 0/5 seeds lower | +10.2% n.s., 1/5 seeds lower |
| `vision:finetuned_day:failsafe_vs_webster` | -20.3% **SIG**, 5/5 seeds lower | -6.9% n.s., 3/5 seeds lower |
| `vision:finetuned_day:honest_vs_truth` | +24.6% n.s., 0/5 seeds lower | +19.5% n.s., 2/5 seeds lower |
| `vision:finetuned_day:honest_vs_webster` | -12.2% n.s., 4/5 seeds lower | +1.0% n.s., 2/5 seeds lower |
| `vision:finetuned_day:trust_vs_truth` | +13.1% n.s., 0/5 seeds lower | +10.2% n.s., 1/5 seeds lower |
| `vision:finetuned_day:trust_vs_webster` | -20.3% **SIG**, 5/5 seeds lower | -6.9% n.s., 3/5 seeds lower |

- **At medium demand the in-domain cameras cost the controller nothing
  measurable**: +0.6 % against truth (n.s., 3/5 seeds better), −31.0 %
  against Webster (was +2.9 % / −29.4 %).
- **At heavy demand** +13.1 % against truth (n.s.), −20.3 % against Webster
  (SIG); the first baseline had +10.2 % / −22.3 %. Heavy runs swing by
  ±20 % per seed on small estimate changes (seed 2 is 22 % better than
  before, seed 4 22 % worse); read the mean, not the change.
- **`failsafe` is `trust` in every fault-free in-domain run** — identical
  person-delay, seed for seed — which is what it is designed to be.
- **`honest` still costs**: +7.9 % against `trust` at medium, +10.2 % at
  heavy (4/5 and 3/5 seeds worse). With the stock detector it costs +21.4 %
  against `failsafe` (significant, all 5 seeds): the ladder's no-memory
  middle rung, 44 % of junction-ticks.
- **Stock-detector `failsafe`** fell to fixed-time on 1.7 % of
  junction-ticks, where the first baseline had none; traced on one seed
  (with the traffic driven by the controller on truth;
  `decisions.json`, `trace_coco_failsafe_low_confidence`) to
  calibration-drift false alarms under the stock detector's noisy headings
  (drift sets health to 0.5, which with any other doubt is under the
  line). +5.4 % against truth.
- **Outage**: trusting dark cameras costs +12.6 % (significant); `failsafe`
  recovers about half (−5.3 % against `trust` in the outage, 4/5 seeds,
  n.s.). The first baseline said three quarters (−9.4 %).

## Gate 4 — incidents (`incident_*.json.gz`, `incident_analysis_budget{1,10}.json`)

**Budget 1 false alarm per hour — `quiet`, now the service default:**

False-alarm budget on TRAIN: 1.0 per simulated hour, whole corridor.

| | incidents | in view | recall (all) | recall (in view) | mean latency (s) | false alarms / h | by rule |
|---|---:|---:|---:|---:|---:|---:|---|
| train | 23 | 20 | 0.26 | 0.30 | 52 | 0.98 | {'midblock_stop': 3} |
| eval | 35 | 27 | 0.23 | 0.19 | 50 | 1.75 | {'midblock_stop': 8} |
| eval hand set default | 35 | 27 | 0.34 | 0.37 | 61 | 36.95 | {'midblock_stop': 12, 'stuck_on_green': 104, 'collision_cue': 52, 'flow_void': 1} |

In-view incidents by kind (eval): stall 5/14, lane_block 0/13

Chosen policy: rules midblock_stop; persistence 5 ticks

| FA/h (train) | recall in view (train) | recall in view (eval) | FA/h (eval) | latency (eval, s) |
|---:|---:|---:|---:|---:|
| 0.00 | 0.00 | 0.00 | 0.00 | -- |
| 0.33 | 0.10 | 0.15 | 1.09 | 61 |
| 0.98 | 0.30 | 0.19 | 1.75 | 50 |

**Budget 10 per hour — `assist`:**

False-alarm budget on TRAIN: 10.0 per simulated hour, whole corridor.

| | incidents | in view | recall (all) | recall (in view) | mean latency (s) | false alarms / h | by rule |
|---|---:|---:|---:|---:|---:|---:|---|
| train | 23 | 20 | 0.30 | 0.35 | 55 | 9.50 | {'stuck_on_green': 26, 'midblock_stop': 3} |
| eval | 35 | 27 | 0.23 | 0.19 | 50 | 10.28 | {'midblock_stop': 8, 'stuck_on_green': 39} |
| eval hand set default | 35 | 27 | 0.34 | 0.37 | 61 | 36.95 | {'midblock_stop': 12, 'stuck_on_green': 104, 'collision_cue': 52, 'flow_void': 1} |

In-view incidents by kind (eval): stall 5/14, lane_block 0/13

Chosen policy: rules stuck_on_green, midblock_stop; persistence 5 ticks

| FA/h (train) | recall in view (train) | recall in view (eval) | FA/h (eval) | latency (eval, s) |
|---:|---:|---:|---:|---:|
| 0.00 | 0.00 | 0.00 | 0.00 | -- |
| 0.33 | 0.10 | 0.15 | 1.09 | 61 |
| 0.98 | 0.30 | 0.19 | 1.75 | 50 |
| 9.50 | 0.35 | 0.19 | 10.28 | 50 |
| 10.16 | 0.45 | 0.33 | 9.62 | 63 |
| 15.40 | 0.50 | 0.26 | 16.40 | 52 |
| 18.02 | 0.55 | 0.37 | 16.62 | 48 |
| 24.57 | 0.65 | 0.37 | 24.27 | 59 |
| 32.43 | 0.70 | 0.41 | 31.27 | 47 |

What the corrected count says: on held-out seeds the rules reach 19 % of
in-view incidents at 1.7 false alarms/h; the 10/h budget's TRAIN choice
adds `stuck_on_green`, which caught 1 more training incident and none
held-out, for six times the alarms — so `quiet` is the service default. The
next point on the TRAIN curve (10.2/h, just over budget) scores 33 % at
9.6/h held-out; the hand-set rules 37 % at 37/h. The incident stream is a
feature for M6's fusion, not a detector.

## Real footage

Not re-run (the clips are not in the repository); see
`baselines/2026-09-23_m8_vision/real_video/`. Of this round's changes,
ByteTrack's duplicate removal and the stitching could shift its track counts
slightly; its detector timings, ONNX parity, camera-health and redaction
results are untouched (the clips are shorter than any activity window, and
the smoke script reads them directly, not through the service's video
mode).

## Reproducing

```bash
cd itms && make setup
.venv/bin/python scripts/m8_perception_gate.py --presets ideal,finetuned_day,coco_pretrained,night_rain \
    --levels medium,heavy --seeds 1 --max-steps 1800 --out perception_gate.json
.venv/bin/python scripts/m8_incident_gate.py --levels medium,heavy --seeds 2 --seed-set train --no-twins --out incident_train.json
.venv/bin/python scripts/m8_incident_gate.py --levels medium,heavy --seeds 3 --seed-set eval --no-twins --out incident_eval.json
.venv/bin/python scripts/m8_incident_analysis.py incident_train.json incident_eval.json --budget 10 --out incident_analysis_budget10.json
.venv/bin/python scripts/m8_incident_analysis.py incident_train.json incident_eval.json --budget 1 --out incident_analysis_budget1.json
.venv/bin/python scripts/m8_closed_loop_gate.py --levels heavy --seeds 5 --out closed_loop.json \
    --arms webster,truth,vision:finetuned_day:trust,vision:finetuned_day:failsafe,vision:finetuned_day:honest
.venv/bin/python scripts/m8_closed_loop_gate.py --levels medium --seeds 5 --resume --out closed_loop.json \
    --arms webster,truth,vision:finetuned_day:trust,vision:finetuned_day:failsafe,vision:finetuned_day:honest,vision:coco_pretrained:honest,vision:coco_pretrained:failsafe,vision:finetuned_day:trust:outage,vision:finetuned_day:honest:outage,vision:finetuned_day:failsafe:outage
.venv/bin/python scripts/m8_estimator_ablation.py closed --level heavy --seed 101 --variant '{"est": {"horizon_quantile": 0.9}}'
scripts/m8_live_e2e.sh
.venv/bin/python scripts/m8_report.py --closed-loop closed_loop.json --perception perception_gate.json \
    --incidents incident_analysis_budget10.json
```

About 4 h on 2 vCPU. Tests: `pytest_full.txt`.
