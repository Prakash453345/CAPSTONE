# Baseline — M8, the controller on measured detectors (2026-09-26)

Builds on `baselines/2026-09-25_m8_uvh26_detector/`, which measured IISc's
UVH-26 YOLO11-S and the stock COCO YOLO11-S on 250 labelled Bengaluru CCTV
frames. This round:

1. fits SimCam's detector error model to those measurements, so the
   digital twin's cameras detect the way the real models do;
2. re-runs the controller on held-out seeds with the fitted detectors;
3. extends the detector test with per-image records and a paired
   comparison with a bar set in advance, ready for the fine-tuned model;
4. prepares the fine-tuning run (`notebooks/m8_uvh26_finetune.ipynb`,
   Google Colab). Its result is not in this baseline.

## 1. SimCam fitted to the real detectors (`simcam_fit.json`)

`scripts/m8_simcam_calibrate.py` fits SimCam's own model: a vehicle is
found with probability `base_recall[type] × sigmoid((h − h50[type]) /
(0.25·h50[type]))` for a box `h` pixels tall. It uses maximum likelihood on
the 3,063 labelled boxes (found or not at the tracker's 0.5 line), and takes
the confusions from what each found vehicle was called. Types with fewer
than 100 boxes (bus, bicycle) share a pooled curve.

What a still image cannot measure keeps the value of the preset each fit
starts from: misses in bursts, false positives, and person recall. The
labels don't say how hidden a vehicle was, so occlusion misses end up in
`base_recall`, and SimCam's visibility curve applies on top. That makes the
fitted presets slightly pessimistic.

| preset (new) | fitted to | car | auto | two-wheeler | bus | truck | h50: car / two-wheeler |
|---|---|---:|---:|---:|---:|---:|---|
| `uvh26_640` | IISc YOLO11-S, 640 px input | 0.92 | 0.86 | 0.78 | 0.73 | 0.70 | 53 / 59 px |
| `uvh26_1280` | the same, 1280 px input | 0.88 | 0.79 | 0.76 | 0.54 | 0.61 | 31 / 5 px |
| `stock_640` | stock COCO YOLO11-S, 640 px | 0.86 | 0.60 (never called an auto) | 0.33 | 0.72 | 0.68 | 64 / 148 px |
| `finetuned_day` (assumed) | — | 0.97 | 0.94 | 0.92 | 0.98 | 0.97 | 14 / 14 px |

At 1280 px the fit put h50 at its 5 px floor for autos, two-wheelers, buses
and bicycles: no size effect was found for them, rather than a measured
half point.

Fit quality, share found by box height (all types, measured / fitted):

| | 20–40 px | 40–80 px | 80–160 px | ≥160 px |
|---|---|---|---|---|
| `uvh26_640` | 0.19 / 0.15 | 0.50 / 0.48 | 0.73 / 0.77 | 0.85 / 0.81 |
| `uvh26_1280` | 0.75 / 0.73 | 0.75 / 0.76 | 0.81 / 0.77 | 0.73 / 0.76 |
| `stock_640` | 0.05 / 0.03 | 0.13 / 0.11 | 0.26 / 0.27 | 0.51 / 0.50 |

**The size curve was where the old assumption was furthest off.** The
assumed "well-trained" detector halved its recall at a 14 px box. The real
model at 640 px input halves it at 53 px for a car and 59 px for a
two-wheeler. A car at the edge of a planned camera's coverage, about 35 px
tall (`docs/vision_system_design.md` §2), is found:
- 97 % of the time as assumed;
- 19 % by the real model at 640 px input;
- 55 % at 1280 px input.

For a two-wheeler at that edge: 92 % assumed, 13 % at 640, 76 % at 1280.

The estimator's confidence does not know this. It judges coverage by
geometry (0.6 m/pixel), so it fed 0.84–0.86 on average with every
measured detector.

## 2. The controller on measured detectors (`closed_loop.json`)

CC-A-CAMP, `failsafe`, held-out seeds 1–5, 19 cameras at 5 fps.
- The new arms are `vision:uvh26_640`, `vision:uvh26_1280` and
  `vision:stock_640`.
- Webster, truth and the old preset arms are carried over from
  `baselines/2026-09-25_m8_ladder_blindcheck/`. None of their code changed:
  a fresh run of `vision:finetuned_day:failsafe` (medium, seed 1) reproduced
  its baseline record exactly, down to every decision count
  (`reproducibility_check.json`).

**medium**

| arm | person-delay | vs truth | vs Webster | p95 wait (s) | stops/veh |
|---|---:|---|---|---:|---:|
| Webster | 106,912 | | | 83.8 | 2.24 |
| truth | 73,355 | | −31.4 % SIG | 59.4 | 1.75 |
| `finetuned_day` (assumed) | 74,580 | +1.7 % n.s. | −30.2 % SIG | 64.2 | 1.70 |
| **`uvh26_1280`** | **75,023** | **+2.3 % n.s.** (2/5 lower) | **−29.8 % SIG** | 64.0 | 1.81 |
| `uvh26_640` | 80,141 | +9.3 % n.s. (1/5) | −25.0 % SIG | 68.6 | 1.95 |
| `coco_pretrained` (assumed) | 77,358 | +5.5 % SIG | −27.6 % SIG | 62.4 | 1.82 |
| `stock_640` | 85,982 | **+17.2 % SIG** (0/5) | −19.6 % SIG | 70.0 | 2.12 |

**heavy**

| arm | person-delay | vs truth | vs Webster | p95 wait (s) | stops/veh |
|---|---:|---|---|---:|---:|
| Webster | 648,447 | | | 427.0 | 3.23 |
| truth | 457,164 | | −29.5 % SIG | 270.6 | 2.73 |
| `finetuned_day` (assumed) | 536,460 | +17.3 % SIG | −17.3 % n.s. | 380.2 | 3.15 |
| **`uvh26_1280`** | **493,570** | **+8.0 % n.s.** (1/5 lower) | **−23.9 % SIG** | 342.2 | 2.98 |
| `uvh26_640` | 534,132 | +16.8 % n.s. (0/5) | −17.6 % SIG | 359.8 | 3.19 |

Head to head:
- `uvh26_640` vs `uvh26_1280`: +6.8 % at medium, 0/5 seeds lower, not
  significant; +8.2 % at heavy, 1/5, not significant.
- `stock_640` vs the old `coco_pretrained` assumption: +11.1 % at medium,
  significant, 0/5 seeds lower.
- No arm had an interlock violation.

- **IISc's detector at 1280 px input costs the controller what the assumed
  well-trained detector did**: +2.3 % against perfect data at medium, +8.0 %
  at heavy, neither significant. At heavy it came out 8 % lower than the
  assumed detector (4/5 seeds, not significant). The controller keeps
  nearly all of its win over Webster: −29.8 % and −23.9 %.
- **At 640 px input it costs more**: +9.3 % at medium and +16.8 % at heavy.
  Neither is significant at n = 5, but it was worse than 1280 on 5/5 and
  4/5 seeds. Most likely the distant vehicles it misses are the arrivals
  the controller plans with. It still beats Webster by 25 % and 18 %.
- **The real stock detector costs three times what was assumed**: +17.2 %
  (significant) against the assumption's +5.5 %. It still beats Webster by
  20 %, most likely because the queue heads near the camera are big enough
  even for it.
- **What this means for a deployment:** with IISc's weights, run the
  detector at 1280 px input (960 did better on still frames, §4, but was
  not run in the loop). On a CPU that is too slow for
  19 cameras (272 ms a frame on the laptop), so it needs a GPU server or an
  edge box per junction. Fine-tuning then has room to improve two-wheelers
  and trucks.

## 3. Found: a standing jam can look like a blind camera

On heavy seed 1, `uvh26_640` sent one junction to fixed-time for 555
controller ticks: the stop-line cross-check fired and stayed latched. The
cause was traced by re-running that seed with the check off, recording its
inputs, and replaying the check on them:
1. In a long standing jam, a vehicle hidden for more than 10 s gets a new
   track when it reappears. A weaker detector hides vehicles more often.
2. The new track has "never moved". After 90 s, or sooner in a spot the
   clutter map has learned, the estimator's furniture rule drops it, so a
   parked car or billboard can't pose as queue.
3. Once every track on the approach had been dropped that way, the camera
   "saw" no vehicle while the loop stayed occupied. The check fired at
   1,864 s and never released, because no vehicle drove.

The alarm cost that run about 3.5 %: with the check off, the same seed gave
597,910 against 618,910. The same mechanism also undercounts a standing
queue. It is not fixed here. Changing what the check counts, or how the
clutter map learns, has to be chosen on TRAIN seeds and then re-measured
on every `failsafe` arm. See PROGRESS for the plan.

## 4. The detector test, ready for the fine-tuned model (`detector/`)

`scripts/m8_detector_eval.py` now keeps per-image counts and every labelled
box's height and outcome. `scripts/m8_detector_compare.py` pairs two runs
image by image, with a 95 % interval from 10,000 resamples of the images.
It then applies the bar set before the fine-tuning started, for adopting a
model B over model A:
- more vehicles found, with the interval above zero;
- a smaller per-image queue PCU error, with the interval below zero;
- precision at least 0.90;
- at most 1.25× the CPU time.

IISc's model at larger input sizes, against 640 (the laptop's CPU):

| input | vehicles found | precision | false boxes / image | PCU error / image | PCU bias | CPU / image |
|---|---:|---:|---:|---:|---:|---:|
| 640 | 0.711 | 0.917 | 0.79 | 2.63 | −1.85 | 56 ms |
| 960 | 0.775 (+0.064, interval above 0) | 0.851 | 1.66 | 2.32 (−0.31, interval below 0) | −0.39 | 161 ms |
| 1280 | 0.765 (+0.054) | 0.797 | 2.39 | 2.69 (+0.06, n.s.) | +0.28 | 272 ms |

On these frames 960 beats 1280 on everything but the average bias, and is
1.7× faster, so it looks the better GPU setting for this model; it has not
been run in the controller loop (no fitted preset). Neither passes the bar
against 640: both fail on precision and CPU time, and 1280 also on the PCU
error. That is what the bar is for.

`detector/test_fingerprints.json` holds the 250 test frames' checksums and
256-bit image fingerprints. The notebook uses them to keep those frames,
and any frame that looks like one of their cameras, out of training. Six
pairs of test frames from 32 to 70 bits apart (of 256), checked by eye,
were all the same camera at different times; 13 pairs fall within the
notebook's threshold of 72.

## Limits

- The fits describe Bengaluru CCTV frames from the camera network the
  model was trained on. SimCam then applies them to the twin's cameras,
  whose heights and angles are the planner's, not Bengaluru's.
- Bursts and false positives are still assumptions (see §1).
- n = 5 seeds per arm. Several 640-against-1280 differences are consistent
  in direction but not significant.

## Reproducing

```bash
# detector test (the laptop: data/uvh26 from scripts/m8_fetch_uvh26_sample.py)
python scripts/m8_detector_eval.py --data data/uvh26 --model uvh26=data/uvh26/UVH-26-MV-YOLOv11-S.onnx --imgsz 640 --out uvh26_640.json
python scripts/m8_detector_eval.py --data data/uvh26 --model uvh26=data/uvh26/UVH-26-MV-YOLOv11-S.onnx --imgsz 1280 --out uvh26_1280.json
python scripts/m8_detector_eval.py --data data/uvh26 --model stock=data/uvh26/yolo11s.onnx --imgsz 640 --out stock_640.json
python scripts/m8_detector_compare.py uvh26_640.json uvh26_960.json
# the fit, then the controller
python scripts/m8_simcam_calibrate.py uvh26_640.json uvh26_1280.json stock_640.json --out simcam_fit.json
python scripts/m8_closed_loop_gate.py --resume --levels medium --seeds 5 --out closed_loop.json \
    --arms webster,truth,vision:uvh26_1280:failsafe,vision:uvh26_640:failsafe,vision:stock_640:failsafe
python scripts/m8_closed_loop_gate.py --resume --levels heavy --seeds 5 --out closed_loop.json \
    --arms webster,truth,vision:uvh26_1280:failsafe,vision:uvh26_640:failsafe
```
