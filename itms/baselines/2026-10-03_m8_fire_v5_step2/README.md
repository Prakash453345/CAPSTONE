# M8 fire and smoke detector, v5 Step 2 (second-stage crop classifier on the v4 detector), 2026-10-03/04

**Verdict: PASS on all five judged targets (A, N, P, B4, C). D (Inferno) has not arrived, so it stays "provisional".**
Targets were locked before the run in `TARGETS_LOCKED.md`. The detector is unchanged (v4 weights, sha256 `bc5c70ec...a001ca1fe`);
a small EfficientNet-B0 (`s2_cls.pt`) checks every candidate box (detector conf >= 0.05). Notebook: `notebooks/m8_fire_smoke_v5_step2.ipynb`
(md5 54dfdbd6fc38c32bf5a45a3ebc0193e0); results: `s2_report.json`.

## Chosen on validation only
(p_fire, p_smoke) = **(0.80, 0.90)**. Validation recall 97.0% (1,236 positives after near-copy removal), 4.1% of D-Fire validation negatives alarm,
1 of 958 Bengaluru validation frames alarms (cap 2). Recall by distance to training on validation: near-copy 97.4%, same video 95.7%, unseen scene 97.6%.

## Judged targets
| # | Test | Target | Result | |
|---|---|---|---|---|
| A | recall, D-Fire test with fire or smoke (2,301) | >= 85% | **85.70%** (1,972; Wilson 95% about 84.3-87.1) | PASS |
| N | false alarms, D-Fire test negatives (2,005) | <= 10% | **9.53%** (191; about 8.3-10.9) | PASS |
| P | image-level precision, D-Fire test | >= 90% | **91.17%** | PASS |
| B4 | 250 NEW Bengaluru frames | at most 2 | **1 of 250** | PASS |
| C | held-out FASDD street/vehicle fires (V+R, 78) | >= 80% | **78 of 78**, Wilson 95% [95.3%, 100%] | PASS |
| D | Inferno | >= 80% | not run | provisional |

## Against Step 1 (same images)
| | Step 1 (fire 0.44, smoke 0.11) | Step 2 |
|---|---|---|
| D-Fire recall | 89.27% | 85.70% |
| D-Fire negatives alarming | 19.10% | 9.53% |
| precision | 84.3% | 91.2% |
| F1 | 0.867 | 0.884 |
| street recall (C) | 97.4% | 100% |
Step 2 halves D-Fire false alarms and gives up 3.6 points of recall. Recall by class: fire images 96.05%, smoke images 85.78%.

## Reported, not judged
- B3 (seen by Step 1): 0 alarms, including the yellow-plate frame 803445 that Step 1 alarmed on. v4 fresh 250: 0 alarms.
- Held-out C by label: B 61/61, F 64/64, I 41/41, O 93/97, R 23/23, V 55/55; not street 330/347; X (no visible fire) 71/84.
- The one B4 alarm, `147883.jpg` (p_fire 0.865, detector conf 0.24): a night greyscale frame, the box sits on a bright hazy patch beside a vehicle's headlight beam on the road. I looked at it: not fire.
- Training crops: 60,038 fire and 32,974 smoke positives, 17,771 negatives (735 detector false alarms in label-free images, 7,412 flame-coloured blobs in Bengaluru frames, 9,624 random boxes; all used), 24,483 ignored candidates in labelled images. Validation crop accuracy 97.9% (fire 98.4%, smoke 97.3%, not 97.9%).
- A seeded sample of training crops looked right by eye (flames and smoke as positives; plates, a truck container, an auto-rickshaw, sunset and plain sky as negatives); some positive crops are tiny and blurred, which is label noise.

## Cautions
- A and N pass narrowly (0.7 points and 0.5 points) and both intervals cross their targets, so these are point-estimate passes.
- Detector-only false alarms are rare in training images (735 candidates), so the classifier mostly learned its negatives from blobs and random boxes. Night, infrared and headlight glare appear to be a weak spot (the B4 alarm); untested beyond that.
- Validation recall (97.0%) is 11 points above test recall (85.7%); the D-Fire test split is harder. Expect about 86% on D-Fire-style material.
- B4 is 250 frames: 1 alarm leaves an upper bound near 2.2%.
- Deployment adds a second model (about 16 MB) and one crop classification per candidate box at conf >= 0.05; CPU latency was not measured.
- Everything is Bengaluru CCTV with UVH-26 privacy blurs; other cities and weather are untested. No street-fire video exists, so persistence and the operator-confirmation layer (ADR-006) remain untested.
