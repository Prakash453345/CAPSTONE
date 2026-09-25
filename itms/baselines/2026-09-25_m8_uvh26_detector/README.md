# Baseline — M8, a real Indian-traffic detector, measured (2026-09-25)

Until now every "in-domain detector" number in M8 was an assumption
(SimCam's `finetuned_day` preset). IISc's UVH-26 (Bengaluru Safe City
CCTV) ships a trained YOLO11-S; this measures it, and the stock COCO
YOLO11-S it would replace, on labelled Indian CCTV frames — through the
pipeline's own detector adapters and at the confidence line the tracker
builds tracks from.

## What was run

- **Images:** 250 UVH-26 validation frames (1080p, fixed random sample,
  seed 26; `sample.json` lists them), 3,063 labelled vehicles (2 more
  labelled "Others" are ignore regions). Fetched by
  `scripts/m8_fetch_uvh26_sample.py` (0.8 GB instead of the 90 GB
  dataset).
- **Models:** stock `yolo11s.pt` (COCO) and UVH-26's `UVH-26-MV-YOLOv11-S.pt`
  (`checkpoint.json`: a 5-epoch continuation of an earlier run, trained at
  640 px). Both exported to ONNX (`dynamic=True`) and run with
  `OnnxDetector`. On 5 of these frames it matched the PyTorch models box
  for box: stock 176 / 176 against Ultralytics' own post-processing;
  UVH-26 76 / 76 at 640 and 109 / 109 at 1280, where both backends share
  the decoder below and the raw network outputs differ by at most 0.0013.
- **Scoring:** `vision_service.eval.detection` via
  `scripts/m8_detector_eval.py`. AP50 is threshold-free; everything else is
  at score ≥ 0.5, ByteTrack's high-score line. "Queue PCU error" is the
  per-image difference between the PCU of what was detected and of what is
  there (truth: 10.2 PCU per image) — the quantity `queue_pcu` is built
  from.
- **Machine:** the laptop (Apple silicon, 4 cores, in a Linux VM),
  ONNX Runtime 1.23 on CPU.

## Results (`*_640.json`, `*_1280.json`)

| detector | input | vehicles found | precision | false boxes / image | queue PCU error | mAP50 | CPU per image |
|---|---:|---:|---:|---:|---:|---:|---:|
| stock YOLO11-S | 640 | 32 % | 0.89 | 0.48 | −4.43 (−44 %) | 0.40 | 63 ms |
| stock YOLO11-S | 1280 | 41 % | 0.85 | 0.92 | −3.24 (−32 %) | 0.46 | 309 ms |
| **UVH-26 YOLO11-S** | **640** | **71 %** | **0.92** | 0.79 | −1.85 (−18 %) | **0.73** | **58 ms** |
| UVH-26 YOLO11-S | 1280 | 76 % | 0.80 | 2.39 | +0.28 (+3 %) | 0.70 | 279 ms |

Per class at 640, share of each class found *as that class*:

| class | labelled | stock | UVH-26 | UVH-26 precision |
|---|---:|---:|---:|---:|
| two-wheeler | 1,467 | 13 % | 66 % | 0.94 |
| car | 694 | 72 % | 84 % | 0.91 |
| auto-rickshaw | 504 | **0 %** (18 % found as another type) | 75 % | 0.94 |
| truck | 279 | 36 % | 55 % | 0.71 |
| bus | 87 | 40 % | 63 % | 0.69 |
| bicycle | 32 | 25 % | 25 % (44 % as some vehicle) | 1.00 |

By box height (all classes, 640): stock finds 13 % of vehicles 40–80 px
tall and 39 % of those taller; UVH-26 50 % and 79 %. At 1280 UVH-26 finds
75 % of the 40–80 px ones.

- **The stock model is not usable on Indian CCTV.** It finds a third of
  the vehicles, one two-wheeler in eight, and has no auto-rickshaw class at
  all. A queue built on it would be under-counted by 44 %.
- **The UVH-26 model roughly doubles what is found**, recognises autos
  (75 %, precision 0.94), and runs as fast. At 640 it still under-counts
  queue PCU by 18 %: of the PCU it misses, trucks are 45 % (3 PCU each)
  and two-wheelers 20 % (a third of them missed). At 1280 the average
  count comes out right (+3 %), but only because three times the false
  boxes offset the misses: the per-image error is no smaller (2.7 PCU
  against 2.6), and it runs 5× slower.
  640 is the choice on a CPU; 1280 is worth testing on a GPU.

## Found and fixed: a car counted five ways

UVH-26 labels a car as hatchback, sedan, SUV, MUV or van, and the model
often spreads its confidence over them ("0.45 sedan, 0.40 hatchback"). The
decoder took the best single type and applied the 0.5 line to it, so a
vehicle the model was sure was a car was dropped — and one car could also
survive NMS twice, as two types. On 5 frames, 65 raw candidate boxes had a
car type ≥ 0.5 and 63 more had car types summing to ≥ 0.5 with no single
type there (candidates before NMS, several per vehicle). Scores are now
summed per ITMS class before the threshold and before NMS
(`vision_service/detect/yolo.py`, `decode`; both backends share it). A
one-to-one map such as COCO decodes exactly as before: the stock run at
640 was repeated after the change and every number but the timing is
identical (`stock_yolo11s_640_rerun_after_fix.json`).

| UVH-26 YOLO11-S, 640 | per type (before) | per ITMS class (now) |
|---|---:|---:|
| car found | 58 % | 84 % |
| vehicles found | 64 % | 71 % |
| precision | 0.92 | 0.92 |
| queue PCU error | −3.17 | −1.85 |

At 1280 the same fix moved vehicles found from 70 % to 76 % and the PCU
error from −1.71 to +0.28 (`superseded/`).

## On unlabelled video (`clips` in `*_640.json`)

The three public clips of the first real-footage test, 75 evenly spaced
frames each, boxes at ≥ 0.5 (counts, not accuracy):

| clip | stock | UVH-26 |
|---|---|---|
| overhead two-lane road, 320×176 | 0 boxes | 2 boxes |
| pole camera, street | 20 boxes in 16 frames | 25 in 18 |
| overpass view of a highway | 256 boxes, every frame | 297, every frame |

The tiny overhead clip defeats both. The other two are not Indian traffic
and both models find their cars.

## What this says about SimCam's presets

The presets were assumptions; these are the first measurements to hold them
against (Bengaluru CCTV, UVH-26's own domain):

| class | `finetuned_day` assumed | UVH-26 measured | `coco_pretrained` assumed | stock measured |
|---|---:|---:|---:|---:|
| car | 0.97 | 0.84 | 0.92 | 0.72 |
| auto-rickshaw | 0.94 | 0.75 | 0.85, 55 % called car | 0 as auto; 18 % found at all |
| two-wheeler | 0.92 | 0.66 | 0.82 | 0.13 |

The assumed values are recall for a vehicle in full view; SimCam then
lowers them for size and occlusion. For cars that lands close to the real
thing: the twin's measured car recall was 0.89 (`finetuned_day`) and 0.76
(`coco_pretrained`) against 0.84 and 0.72 here. The gap is in two-wheelers
and autos, whose recall the twin never reported separately: assumed 0.92
and 0.94 against 0.66 and 0.75 for the in-domain model, and for the stock
one 0.82 and "55 % called car" against 0.13 and none recognised. So M8's
closed-loop cost of a stock detector (+5.5 % person-delay) was measured
with a detector far kinder to two-wheelers and autos than the real one,
and the "well-trained" rows are closer to a best case than to this model.

## Limits

- **Same domain as the model's training data.** The frames are UVH-26
  validation images from the Bengaluru camera network the model was
  trained on. Vijayawada's cameras differ in height, angle and traffic;
  only footage from there says how much of this carries over.
- **250 images.** Class totals are large for two-wheelers, cars and autos,
  small for buses (87) and bicycles (32).
- **Whole frames.** Every labelled vehicle counts, including those far
  down the road that a planned camera's coverage zone (≤ 0.6 m/pixel)
  would leave out; the height table is the fairer view for near vehicles.
- **A released checkpoint, not a tuned one** (`checkpoint.json`).

## Reproducing

```bash
python3 scripts/m8_fetch_uvh26_sample.py            # on a machine that reaches huggingface.co
yolo export model=data/uvh26/UVH-26-MV-YOLOv11-S.pt format=onnx dynamic=True imgsz=640
yolo export model=yolo11s.pt format=onnx dynamic=True imgsz=640
python scripts/m8_detector_eval.py --data data/uvh26 --imgsz 640 \
    --model uvh26=data/uvh26/UVH-26-MV-YOLOv11-S.onnx --out uvh26_yolo11s_640.json \
    --clips highway.avi pbc.mp4 overpass.mp4
python scripts/m8_detector_eval.py --data data/uvh26 --imgsz 640 \
    --model stock=data/uvh26/yolo11s.onnx --out stock_yolo11s_640.json \
    --clips highway.avi pbc.mp4 overpass.mp4
# and --imgsz 1280 for the 1280 rows
```
