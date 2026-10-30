# M8 vehicle detectors on the full UVH-26 validation split, 6-class and 14-class (2026-10-28)

Targets were locked before scoring (`2026-10-27_m8_uvh26_fullval/TARGETS_LOCKED.md`). Run: Kaggle CPU, notebook `m8_uvh26_fullval.ipynb`, 5,297 validation frames (63,497 boxes; 'Others' 70 = ignore regions in the 6-class scoring), four ONNX models at 640 px. Scored by `scripts/m8_detector_fullval.py score`; I re-scored the returned detections independently and every 6-class and 14-class figure matched the notebook's to 4 decimals (6-class to 1e-16).

**Verdict on the locked checks: R, F1, F2 (all 8 comparisons), F3 pass. P: not the same measurement as the paper (13-class mAP50:95 0.474 vs 0.339). B: the BatchNorm repair adds +0.05 mAP on 14 classes.** Nothing is re-adopted from this run; fine-tune v3 stays the deployed 640 px detector.

## 6-class (ITMS classes), all 5,297 frames, score line 0.5 (95 % image-bootstrap intervals)
| model | found | precision | false boxes / image | queue PCU error / image | PCU bias | AP50 |
|---|---|---|---|---|---|---|
| IISc as released | 0.704 [0.700, 0.709] | 0.920 [0.917, 0.923] | 0.73 | 2.74 [2.67, 2.82] | -1.91 | 0.759 |
| IISc BatchNorm-repaired | 0.730 [0.726, 0.734] | 0.943 [0.940, 0.946] | 0.53 | 2.59 [2.51, 2.66] | -2.26 | 0.790 |
| fine-tune v2 | 0.792 [0.788, 0.796] | 0.919 [0.916, 0.921] | 0.84 | 2.07 [2.01, 2.13] | -1.45 | 0.817 |
| **fine-tune v3 (deployed)** | 0.785 [0.781, 0.789] | 0.924 [0.921, 0.926] | 0.78 | 2.10 [2.04, 2.17] | -1.54 | 0.821 |

True mean queue is 10.27 PCU per frame, so v3 still reads about 1.5 PCU (15 %) low on average and is off by about 2.1 PCU on a typical frame.

Share found **as the right type** (63,427 vehicles: 30,211 two-wheelers, 13,642 cars, 10,467 autos, 6,087 trucks, 2,339 buses, 681 bicycles):
| model | two-wheeler | car | auto | truck | bus | bicycle |
|---|---|---|---|---|---|---|
| IISc as released | 0.66 | 0.79 | 0.75 | 0.59 | 0.65 | 0.34 |
| IISc BatchNorm-repaired | 0.69 | 0.80 | 0.77 | 0.65 | 0.65 | 0.33 |
| fine-tune v2 | 0.76 | 0.86 | 0.81 | 0.70 | 0.68 | 0.49 |
| fine-tune v3 | 0.75 | 0.86 | 0.82 | 0.68 | 0.69 | 0.47 |

By box height (found as some vehicle, v3): under 20 px 0.00, 20-40 px 0.31, 40-80 px 0.61, over 80 px 0.84 (v2: 0.00 / 0.39 / 0.64 / 0.84; IISc as released 0.00 / 0.14 / 0.47 / 0.78).

## Judged
| # | check | result |
|---|---|---|
| R | full run reproduces the earlier 250-frame baselines | **pass**, exact: on the old 250 frames found and precision equal the stored results to the last digit for all four models (e.g. IISc 0.7107 / 0.9166, v3 0.7839 / 0.9242) |
| F1 | the 250-frame figure was representative | **pass**, 8/8: every model's full-set found and precision lies inside the old-250 bootstrap interval (e.g. v3 found 0.785 in [0.765, 0.802]) |
| F2 | the 2026-09-26 bar holds on ALL and on UNTOUCHED (4,797 frames no decision saw) | **pass in all 8 comparisons** (v2 and v3 each vs IISc and vs repaired IISc, both sets): found up with the interval above zero, PCU error down with the interval below zero, precision >= 0.90. v3 vs IISc: +0.081 found [+0.078, +0.083], PCU error -0.65 [-0.69, -0.60], precision 0.924. v3 vs repaired IISc: +0.055 found, -0.49 PCU error, but precision -0.019 (0.924 vs 0.943) and +0.25 false boxes / image |
| F3 | same ranking on UNTOUCHED as on ALL | **pass**: v2, v3, repaired IISc, IISc by found and by PCU error, on both |
| P | published comparison | reported below: **not like-for-like** |
| B | BatchNorm repair on 14 classes | +0.050 mAP50, +0.052 mAP50:95 |

Not locked, but looked at: v3 against v2 on the full set. v3 finds 0.007 fewer vehicles [-0.008, -0.005], has 0.06 fewer false boxes per image, precision +0.005, PCU error +0.03 [-0.001, +0.063]. So v3 is the cleaner of the two and v2 the slightly more sensitive one; the stress gains of v3 (night, glare, noise) come at this small clean-frame cost, as the v3 test said (-0.008).

## 14-class COCO evaluation (IISc's model; pycocotools, conf 0.001, NMS 0.7, 300 boxes, 640 px)
My decoder was checked against Ultralytics' own validation on 30 frames before the run: mAP50 0.6691 vs 0.6689, mAP50:95 0.5018 vs 0.5014.
| model | classes | mAP50 | mAP75 | mAP50:95 |
|---|---|---|---|---|
| IISc as released | 13 (no 'Others', as the paper) | 0.586 | 0.525 | 0.474 |
| IISc as released | 14 | 0.547 | 0.488 | 0.442 |
| IISc BatchNorm-repaired | 13 | 0.640 | 0.592 | 0.530 |
| IISc BatchNorm-repaired | 14 | 0.597 | 0.552 | 0.494 |

Per class (AP50 / AP50:95), beside the paper's Table 6 (YOLO11-S):
| class | boxes | as released | repaired | paper |
|---|---|---|---|---|
| Hatchback | 6,094 | 0.654 / 0.559 | 0.666 / 0.570 | 0.451 / 0.362 |
| Sedan | 3,151 | 0.621 / 0.551 | 0.634 / 0.563 | 0.449 / 0.363 |
| SUV | 2,639 | 0.483 / 0.411 | 0.548 / 0.477 | 0.232 / 0.198 |
| MUV | 1,315 | 0.449 / 0.399 | 0.466 / 0.419 | 0.147 / 0.126 |
| Bus | 1,830 | 0.671 / 0.502 | 0.806 / 0.647 | 0.311 / 0.212 |
| Truck | 2,596 | 0.377 / 0.245 | 0.657 / 0.514 | 0.522 / 0.386 |
| Three-wheeler | 10,467 | 0.899 / 0.743 | 0.917 / 0.766 | 0.804 / 0.575 |
| Two-wheeler | 30,211 | 0.890 / 0.656 | 0.891 / 0.661 | 0.695 / 0.425 |
| LCV | 3,491 | 0.632 / 0.500 | 0.729 / 0.590 | 0.617 / 0.439 (paper row "TCV") |
| Mini-bus | 174 | 0.270 / 0.219 | 0.296 / 0.241 | 0.030 / 0.018 |
| Tempo-traveller | 335 | 0.627 / 0.528 | 0.686 / 0.602 | not in the paper's list under this name |
| Bicycle | 681 | 0.612 / 0.469 | 0.586 / 0.449 | 0.285 / 0.208 |
| Van | 443 | 0.431 / 0.381 | 0.437 / 0.386 | 0.485 / 0.391 |
| Others | 70 | 0.044 / 0.027 | 0.042 / 0.030 | excluded by the paper |

(Paper rows: "Cycle" is bicycle; "T. Traveller" 0.803 / 0.706 is tempo-traveller; I matched them by name.)

**How to read the comparison with IISc.**
- The paper's set is a 400-image gold test (preliminary v1.0, 4 Nov 2025), not UVH-26-Val. It states no thresholds or tool. Its YOLO11-S overall is mAP50 0.4486, mAP50:95 0.3391; ours on the validation split is 0.586 and 0.474 (13 classes). The gap (+0.14) is far outside the +-0.03 "consistent" band I set, and it cannot be assigned to the model: different images, different tool, possibly different weights (our file's `checkpoint.json` says a 5-epoch continuation of an earlier run).
- The 14-class result is lower than the 13-class because 'Others' (70 boxes) is nearly undetectable (AP50 0.04). The paper left it out for that reason.
- The as-released file's weak spot is **trucks** (AP50 0.377, versus 0.657 after the BatchNorm repair) and buses. That fits the BatchNorm damage found on 2026-09-26 (infinite running variances in the released checkpoint). Anyone evaluating that file directly gets numbers below what IISc's own training run measured.
- The ITMS 6-class AP50 (0.759 / 0.790 / 0.817 / 0.821) is a different quantity from 14-class mAP50 (it merges car types and drops 'Others'); do not set them side by side.

## What this changes
- The 250-frame numbers were representative (F1) and the earlier decisions stand (F2, F3). The larger sample's main gain is the small classes: buses (87 to 2,339) and bicycles (32 to 681), where v3 finds 0.69 and 0.47 as the right type. **Bicycles are the weak class** (about half found, 0.82 precision), and anything under 20 px is not found at all.
- v3's queue estimate still reads low (-1.54 PCU, -15 %). The repaired IISc model reads lower (-2.26) despite higher precision, so precision alone does not fix the queue estimate.
- v3 vs v2 is a trade, not a loss: 0.7 points fewer vehicles found for 0.06 fewer false boxes per image.

## Limits
- Same camera network as training (no camera ids), so this is in-domain; a new city is not tested. Intervals resample images, not cameras, and are too narrow for that reason.
- Only IISc's model has a 14-class result. The paper comparison is context, not a benchmark match.
- ONNX Runtime on CPU, 640 px, frames as PNG (not the JPEG copies some v3 stress tests used); the Kaggle machine's timings (about 100 ms per frame per model) are not comparable with the laptop's.
- Scoring script found and fixed an inefficiency in `load_dets` (each image kept a whole shard array alive; it ran out of memory on a 7 GB machine, not on Kaggle). Results are unchanged.

## Files
`2026-10-27_m8_uvh26_fullval/`: `TARGETS_LOCKED.md`, `fullval_results.json` (every table above), `meta.json` (model hashes, settings, versions). Detections are in `uvh26_fullval_results.zip` (run/dets_*.npz). Reproduce: `notebooks/m8_uvh26_fullval.ipynb`, then `python scripts/m8_detector_fullval.py score ...`.
