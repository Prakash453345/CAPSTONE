# Baseline — M8, making camera confidence useful to the controller (2026-09-25)

Builds on `baselines/2026-09-25_m8_review/` (every number not re-measured
here stands as it is there). Two changes, and what they do on held-out
seeds:

1. **The controller's degradation ladder, fixed** (`acamp.py`). With no
   demand memory configured, the middle rung (confidence 0.5–0.8) dropped to
   M2's min-green cycler, which ends any green older than 7 s. It now
   controls on the live estimate — a blend with no history *is* the live
   reading, by `memory.blend`'s own rule. The cycler stays behind
   `use_memory_blend=False` for M5's sensor-degradation experiment.
2. **A stop-bar cross-check for blind cameras**
   (`itms_domain.camera.BlindCameraCheck`, in both controller adapters).
   A camera whose detector stops finding vehicles keeps sending frames and
   looks healthy; nothing in the vision service can tell its "empty road"
   from a real one. The controller also has a stop-bar loop: a link whose
   loop keeps seeing vehicles while the camera tracks none on its approach
   becomes a hard failure until the camera sees one. The link-state event
   now carries `vehicles_seen` for this, and SimCam gained a `blind` fault.

Also measured and left unchanged: the calibration-drift monitor
(`drift_check.json`).

## Setup

As the review baseline: CC-A-CAMP as `baselines/2026-09-18_gap_out/`, 19
planned cameras, SimCam at 5 fps, held-out `EVAL_SEEDS` 1–5, TRAIN seeds
101–102 for every choice, 2 vCPU (`environment.txt`). Webster, truth and
`trust` runs are carried over from the review baseline: none of the code
they use changed, and every `failsafe` run in which the cross-check did not
fire reproduces its `trust` run exactly, seed for seed.

## The cross-check, chosen on TRAIN seeds (`scripts/m8_blind_check_calibration.py`)

8 fault-free runs (medium and heavy, in-domain and stock detectors) and 2
with the busiest junction's detector blinded from 900 s to 2,700 s; the
controller runs on the cameras with the check *off* (so it cannot change
the traffic it is measured on), and the check is replayed offline for every
setting (`blind_check_calibration.series.json.gz`).

| design | false alarms / h, corridor (fault-free) | blinded links caught |
|---|---:|---|
| v1: `has_demand` (a vehicle anywhere on a lane up to 600 m long), 60 s | 34 | 32 / 32 |
| v2: stop-bar loop (last 20 m), "seen" = queue + approaching, 30 s of loop time | 10.5 | 32 / 32 |
| **v3: stop-bar loop, "seen" = any vehicle tracked on the approach, 30 s** | **1.6** | **32 / 32**, median 85 s, worst 923 s |
| v3 at 20 s | 3.6 | 32 / 32, median 39 s |
| v3 at 45 s | 0.0 | 24 / 32 |

v1 compared the camera with a zone it cannot see. v2's "seen" missed a car
creeping over the loop (neither stopped nor due within 8 s) and a car the
tracker put in the next lane. v3 at 30 s is the shortest hold that caught
every blinded link with under two false alarms an hour; all of them came
with the stock detector, in two of its four runs (27 s and 47 s of a
junction flagged), none with the in-domain one. `gap_s` (how long an empty
loop wipes the evidence) changed neither the false alarms nor the catches
between 5 and 20 s; at 5 s the median detection was 94 s rather than 85 s.
v1 also timed an episode from its start rather than counting occupied
seconds, which is what made it 266 an hour at a 30 s hold. The first
held-out run found one more
defect: a caught link was released whenever its loop went quiet, and a
blinded junction flickered in and out of fixed-time (3.8 % of junction-ticks
against a dark camera's 7 %). It now stays failed until the camera sees a
vehicle; the runs it changed were re-run
(`superseded/closed_loop_prelatch_fired.json`).

## Held-out: the controller on cameras (`closed_loop.json`)

**medium** (paired held-out seeds)

| arm | n | person-delay | p95 wait (s) | stops/veh | interlock viol. | confidence fed (mean) | fixed-time fallback |
|---|---:|---:|---:|---:|---:|---:|---:|
| `webster` | 5 | 106,912 | 83.8 | 2.24 | 0 | -- | -- |
| `truth` | 5 | 73,355 | 59.4 | 1.75 | 0 | -- | -- |
| `vision:finetuned_day:trust` | 5 | 73,789 | 61.2 | 1.71 | 0 | 0.90 | 0.0% of ticks |
| `vision:finetuned_day:failsafe` | 5 | 74,580 | 64.2 | 1.70 | 0 | 0.90 | 0.0% of ticks |
| `vision:finetuned_day:honest` | 5 | 74,580 | 64.2 | 1.70 | 0 | 0.90 | 0.0% of ticks |
| `vision:coco_pretrained:failsafe` | 5 | 77,358 | 62.4 | 1.82 | 0 | 0.86 | 1.6% of ticks |
| `vision:coco_pretrained:honest` | 5 | 77,358 | 62.4 | 1.82 | 0 | 0.86 | 1.6% of ticks |
| `vision:finetuned_day:trust:outage` | 5 | 83,111 | 75.4 | 1.73 | 0 | 0.78 | 0.0% of ticks |
| `vision:finetuned_day:failsafe:outage` | 5 | 78,693 | 59.2 | 1.78 | 0 | 0.78 | 7.0% of ticks |
| `vision:finetuned_day:trust:blind` | 5 | 83,111 | 75.4 | 1.73 | 0 | 0.90 | 0.0% of ticks |
| `vision:finetuned_day:failsafe:blind` | 5 | 79,814 | 59.4 | 1.79 | 0 | 0.90 | 6.9% of ticks |
| `vision:finetuned_day:failsafe:blind:nocheck` | 5 | 83,111 | 75.4 | 1.73 | 0 | 0.90 | 0.0% of ticks |

| head to head (second vs first) | person-delay | stops/veh |
|---|---|---|
| `vision:finetuned_day:honest` vs `vision:finetuned_day:trust` | +1.1% n.s., 0/5 seeds lower | -0.5% n.s., 1/5 seeds lower |
| `vision:finetuned_day:failsafe` vs `vision:finetuned_day:trust` | +1.1% n.s., 0/5 seeds lower | -0.5% n.s., 1/5 seeds lower |
| `vision:finetuned_day:honest` vs `vision:finetuned_day:failsafe` | +0.0% n.s., 0/5 seeds lower | +0.0% n.s., 0/5 seeds lower |
| `vision:coco_pretrained:honest` vs `vision:coco_pretrained:failsafe` | +0.0% n.s., 0/5 seeds lower | +0.0% n.s., 0/5 seeds lower |
| `vision:finetuned_day:trust:outage` vs `vision:finetuned_day:trust` | +12.6% **SIG**, 1/5 seeds lower | +0.8% n.s., 2/5 seeds lower |
| `vision:finetuned_day:failsafe:outage` vs `vision:finetuned_day:trust:outage` | -5.3% n.s., 4/5 seeds lower | +3.2% n.s., 2/5 seeds lower |
| `vision:finetuned_day:trust:blind` vs `vision:finetuned_day:trust` | +12.6% **SIG**, 1/5 seeds lower | +0.8% n.s., 2/5 seeds lower |
| `vision:finetuned_day:failsafe:blind` vs `vision:finetuned_day:trust:blind` | -4.0% n.s., 4/5 seeds lower | +3.5% n.s., 1/5 seeds lower |
| `vision:finetuned_day:failsafe:blind` vs `vision:finetuned_day:failsafe:blind:nocheck` | -4.0% n.s., 4/5 seeds lower | +3.5% n.s., 1/5 seeds lower |

| comparison | person-delay | stops/veh |
|---|---|---|
| `truth_vs_webster` | -31.4% **SIG**, 5/5 seeds lower | -21.6% **SIG**, 5/5 seeds lower |
| `vision:coco_pretrained:failsafe_vs_truth` | +5.5% **SIG**, 0/5 seeds lower | +3.7% n.s., 0/5 seeds lower |
| `vision:coco_pretrained:failsafe_vs_webster` | -27.6% **SIG**, 5/5 seeds lower | -18.7% **SIG**, 5/5 seeds lower |
| `vision:coco_pretrained:honest_vs_truth` | +5.5% **SIG**, 0/5 seeds lower | +3.7% n.s., 0/5 seeds lower |
| `vision:coco_pretrained:honest_vs_webster` | -27.6% **SIG**, 5/5 seeds lower | -18.7% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:failsafe:blind:nocheck_vs_truth` | +13.3% **SIG**, 0/5 seeds lower | -1.5% n.s., 4/5 seeds lower |
| `vision:finetuned_day:failsafe:blind:nocheck_vs_webster` | -22.3% **SIG**, 5/5 seeds lower | -22.8% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:failsafe:blind_vs_truth` | +8.8% **SIG**, 0/5 seeds lower | +2.0% n.s., 1/5 seeds lower |
| `vision:finetuned_day:failsafe:blind_vs_webster` | -25.3% **SIG**, 5/5 seeds lower | -20.1% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:failsafe:outage_vs_truth` | +7.3% **SIG**, 0/5 seeds lower | +1.6% n.s., 2/5 seeds lower |
| `vision:finetuned_day:failsafe:outage_vs_webster` | -26.4% **SIG**, 5/5 seeds lower | -20.4% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:failsafe_vs_truth` | +1.7% n.s., 2/5 seeds lower | -2.8% n.s., 4/5 seeds lower |
| `vision:finetuned_day:failsafe_vs_webster` | -30.2% **SIG**, 5/5 seeds lower | -23.8% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:honest_vs_truth` | +1.7% n.s., 2/5 seeds lower | -2.8% n.s., 4/5 seeds lower |
| `vision:finetuned_day:honest_vs_webster` | -30.2% **SIG**, 5/5 seeds lower | -23.8% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:trust:blind_vs_truth` | +13.3% **SIG**, 0/5 seeds lower | -1.5% n.s., 4/5 seeds lower |
| `vision:finetuned_day:trust:blind_vs_webster` | -22.3% **SIG**, 5/5 seeds lower | -22.8% **SIG**, 5/5 seeds lower |
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
| `vision:finetuned_day:failsafe` | 5 | 536,460 | 380.2 | 3.15 | 0 | 0.90 | 0.0% of ticks |
| `vision:finetuned_day:honest` | 5 | 536,460 | 380.2 | 3.15 | 0 | 0.90 | 0.0% of ticks |

| head to head (second vs first) | person-delay | stops/veh |
|---|---|---|
| `vision:finetuned_day:honest` vs `vision:finetuned_day:trust` | +3.8% n.s., 0/5 seeds lower | +4.7% n.s., 0/5 seeds lower |
| `vision:finetuned_day:failsafe` vs `vision:finetuned_day:trust` | +3.8% n.s., 0/5 seeds lower | +4.7% n.s., 0/5 seeds lower |
| `vision:finetuned_day:honest` vs `vision:finetuned_day:failsafe` | +0.0% n.s., 0/5 seeds lower | +0.0% n.s., 0/5 seeds lower |

| comparison | person-delay | stops/veh |
|---|---|---|
| `truth_vs_webster` | -29.5% **SIG**, 5/5 seeds lower | -15.5% **SIG**, 5/5 seeds lower |
| `vision:finetuned_day:failsafe_vs_truth` | +17.3% **SIG**, 0/5 seeds lower | +15.3% n.s., 1/5 seeds lower |
| `vision:finetuned_day:failsafe_vs_webster` | -17.3% n.s., 5/5 seeds lower | -2.5% n.s., 2/5 seeds lower |
| `vision:finetuned_day:honest_vs_truth` | +17.3% **SIG**, 0/5 seeds lower | +15.3% n.s., 1/5 seeds lower |
| `vision:finetuned_day:honest_vs_webster` | -17.3% n.s., 5/5 seeds lower | -2.5% n.s., 2/5 seeds lower |
| `vision:finetuned_day:trust_vs_truth` | +13.1% n.s., 0/5 seeds lower | +10.2% n.s., 1/5 seeds lower |
| `vision:finetuned_day:trust_vs_webster` | -20.3% **SIG**, 5/5 seeds lower | -6.9% n.s., 3/5 seeds lower |

The blind arms blind the detector of all four cameras at the busiest
junction from 900 s to 2,700 s — frames keep arriving, nothing is detected.

- **The ladder fix removes the confidence penalty.** `honest` now makes
  exactly the decisions `failsafe` does, on every seed at both levels and
  with both detectors. With the stock detector `honest` was +21.4 % against
  `failsafe` (significant, all 5 seeds; review baseline); it is now
  identical.
- **A blind camera costs what a dark one does** when it is believed
  (`trust:blind` and `trust:outage` have the same outcome on every seed:
  +12.6 %, significant) and
  nothing inside the vision system notices (`failsafe:blind:nocheck` is
  identical to `trust:blind`).
- **The cross-check turns it into a known failure.** The junction spends
  6.9 % of junction-ticks in fixed-time, as it does when a dark camera is
  known to be dark (7.0 %). The check recovers about a third of the blind
  camera's cost (−4.0 % against believing it, 4/5 seeds, not significant at
  n = 5). Being told the camera is dark from the first second recovers
  about half (−5.3 %). Most likely the difference is the time the check
  needs to be sure (a median 85 s on TRAIN seeds), but the two arms cannot
  be told apart at n = 5 (blind with the check against the known outage:
  +1.4 %, 2/5 seeds lower, not significant).
- **What it costs when nothing is wrong:** with the in-domain detector, on
  held-out seed 5 it false-alarmed briefly at both levels (4 and 8
  junction-ticks of fixed-time). At medium that seed came out 5.5 % worse;
  at heavy, 20 % worse, from 8 ticks. Heavy runs swing that much on small
  nudges (the review baseline saw seeds move ±22 % between code versions
  for the same reason), so read the means: +1.1 % at medium, +3.8 % at
  heavy, neither significant. With the stock detector at medium it fired
  on seeds 1 and 4 (5 and 1 junction-ticks); those runs moved 0.0 % and
  +0.2 % against the review baseline.

## The ladder in M5's own experiment (`m5_sensor_degradation_rerun.json`)

`scripts/m5_sensor_degradation.py` on current code: A-CA-MP on SUMO truth
with confidence held at 0.6 on every movement (the middle band), three
middle rungs, held-out seeds 1–5.

| level | live (the rung now) | fixed-time (the rung before) | blend with the demand memory |
|---|---:|---:|---:|
| light | **32,092** | 48,590 | 76,117 |
| medium | **83,735** | 97,008 | 151,658 |

Live against fixed-time: −34.0 % at light (significant, 5/5 seeds), −13.7 %
at medium (4/5, not significant). The memory blend is +57 % and +56 %
against fixed-time (significant, 0/5) — worse than when M5 first measured
it (`scripts/results/m5_sensor_degradation_results.json`, August, where
fixed-time was the better arm at light and tied at medium). M5's own
conclusion holds more strongly: history helps where live data is absent,
not where it is merely noisy.

## The calibration-drift monitor, measured (`drift_check.json`)

The first scripted test of a camera knocked askew in SimCam
(`scripts/m8_drift_check.py`; series in `drift_check.series.json.gz`): a
3° yaw bump at 1,200 s was flagged in 84 s with the in-domain detector and
101 s with the stock one, both on the off-lane rate (up 0.20 over the
camera's baseline at the alarm; heading error up 4.1° and 5.2°). In the
five minutes after the bump the off-lane rise had a median of 0.27–0.30 and
peaked at 0.385 and 0.397. Later the heading error went to about 177°
while the off-lane rate fell back: the tracks landed on a lane but against
its direction, most likely the opposing lane that a 3° turn shifts them
onto at that range. The alarm stayed on to the end of both runs; from
about 1,950 s too few vehicles passed (under the monitor's 40 samples) for
it to be re-judged.

Four fault-free TRAIN runs raised no false alarm; the largest rises were
2.8° and 0.12 against thresholds of 6° and 0.2. The one false alarm on
record (stock detector, held-out seed 1, review baseline) came from
`cam_cluster_11608007559_…_678625358#0`, which on the TRAIN runs had the
largest off-lane rise of the corridor's cameras in two of four and the
second largest in the other two. With no training case to tune against,
the monitor is unchanged.

## Reproducing

```bash
.venv/bin/python scripts/m8_blind_check_calibration.py --out blind_check_calibration.json
.venv/bin/python scripts/m8_closed_loop_gate.py --levels medium --seeds 5 --out closed_loop.json \
    --arms webster,truth,vision:finetuned_day:trust,vision:finetuned_day:failsafe,vision:finetuned_day:honest,vision:coco_pretrained:failsafe,vision:coco_pretrained:honest,vision:finetuned_day:trust:outage,vision:finetuned_day:failsafe:outage,vision:finetuned_day:trust:blind,vision:finetuned_day:failsafe:blind,vision:finetuned_day:failsafe:blind:nocheck
.venv/bin/python scripts/m8_closed_loop_gate.py --levels heavy --seeds 5 --resume --out closed_loop.json \
    --arms webster,truth,vision:finetuned_day:trust,vision:finetuned_day:failsafe,vision:finetuned_day:honest
.venv/bin/python scripts/m5_sensor_degradation.py --out m5_sensor_degradation_rerun.json
.venv/bin/python scripts/m8_drift_check.py --out drift_check.json
.venv/bin/python scripts/m8_report.py --closed-loop closed_loop.json
```

Tests: `pytest_full.txt`.
