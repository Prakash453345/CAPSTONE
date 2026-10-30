# ACCIDENT video model v1 (per-frame EfficientNet-B0, 224 px) — 2026-10-06

**Verdict: FAILED the locked targets (4 of 5). Not shippable as an accident detector.**
Scored once on the benchmark's own test splits after freezing the threshold on validation clips.

| Target | Result | |
|---|---|---|
| B1 in-dist: alarm within 10 s after impact >= 70 % | 50.0 % (1,520 clips) | FAIL |
| B2 in-dist: alarm before impact <= 5 % | 30.1 % | FAIL |
| B3 median delay <= 5 s | 0.47 s | pass |
| B4 geo split: detect >= 60 % / early <= 8 % | 24.1 % / 11.3 % (1,573 clips) | FAIL / FAIL |
| B5 nothing tuned on test | held | pass |

Strict (detected AND no early alarm): 22.4 % in-dist, 15.0 % geo.

## What it shows
- On validation, NO threshold/persistence setting got early alarms under the 4 % cap; the search ended on the grid's top threshold (0.95, 4-of-6 frames) for both splits. The frame model cannot separate "normal traffic just before the crash" from "crash/aftermath" well.
- Geographic shift hurts recall badly (50 % -> 24 %).
- Synthetic CARLA frames helped a little on validation (picked over real-only), not enough.
- Best groups: signalized intersections (geo: 39 % detect), t-bone/head-on. Worst: single-vehicle crashes, highways, rain/snow, poor quality.

## Likely causes (not yet tested)
1. 224-px squash of 1080p+ CCTV: the crash is a few % of the frame width and is lost.
2. Single frames carry no motion; a crash is a sudden change.
3. Small training set (~500 real clips), ~8 epochs, ImageNet-only pretraining.

Targets stay locked for any v2. Files: `results_*.json`, `chosen_*.json`, `itms_accident_224.onnx` (kept out of git; in `accident_results/`).
