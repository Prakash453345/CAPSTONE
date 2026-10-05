# M8 v5 Step 2: second-stage crop classifier. TARGETS LOCKED before the run (2026-10-03)

Approved by the user in chat on 2026-10-03 ("go on", after the draft table was shown). Nothing below may change after a run starts.
Step 1 (thresholds on the v4 weights) passed A, B3 and C (`../2026-10-02_m8_fire_v5_step1/README.md`) but D-Fire negatives alarm 19.1 %
and the one B3 alarm was a blurred yellow number plate. Step 2 adds a small classifier that must agree with the detector.

## Design (fixed, not tuned)
- Detector: the v4 weights (`itms_fire_640.pt`, sha256 `bc5c70ec...a001ca1fe`), 640 px, NMS IoU 0.7, candidate boxes at conf >= 0.05 (a constant).
- Classifier: torchvision EfficientNet-B0 (ImageNet weights), 3 outputs (fire, smoke, not), 112 x 112 crop with a 25 % margin.
  Fixed training recipe: 8 epochs, AdamW lr 3e-4, weight decay 1e-4, cosine schedule, batch 64, label smoothing 0.1, seed 26.
  The LAST epoch is used (no epoch is picked by looking at any score).
- Training crops (TRAINING split only):
  positives = ground-truth fire/smoke boxes (jittered) and detector candidates that match one (IoU >= 0.3, same class);
  negatives = (a) detector candidates in training images that carry NO fire or smoke label, (b) flame-coloured blobs (HSV mask) in Bengaluru
  training frames (plates, lamps, clothing), (c) random boxes of realistic size in label-free training images.
  Detector candidates that sit in an image WITH a fire/smoke label and match no box are IGNORED (they are often real fire without a label).
  Negatives are capped at 3 x the positives, sampled evenly across (a), (b), (c). No validation, test, held-out, B3 or B4 image is used.
- Alarm rule: an image alarms if some candidate box of class c has classifier probability P(c) >= p_c, for c = fire and smoke.
- (p_fire, p_smoke) chosen on VALIDATION only: grid 0.05 .. 0.95 step 0.05 for both. Keep pairs whose Bengaluru validation alarms
  are <= floor(0.003 x n). Among them take the highest recall on validation images with fire or smoke (not Bengaluru) after removing
  near-copies (<= 40 dhash bits) of any non-Bengaluru training image. Ties: fewer alarms on D-Fire validation negatives, then the larger sum.
  Stop (no verdict) if fewer than 60 validation images remain.
- B4 = 250 NEW Bengaluru frames (UVH-26), more than 72 dhash bits from every frame any earlier step used, including B3. Scored once.

## Judged targets
| # | Test | Data | Target |
|---|---|---|---|
| A | recall, any fire or smoke | D-Fire test images with fire or smoke (2,301) | >= 85 % |
| N | false alarms | D-Fire test images with no fire or smoke (2,005) | <= 10 % |
| P | image-level precision | D-Fire test, TP / (TP + false alarms) | >= 90 % |
| B4 | false alarms | 250 new Bengaluru frames | at most 2 (<= 1 %) |
| C | recall on street and vehicle fires | held-out FASDD V or R images (near-copies of training removed) | >= 80 % |
| D | Inferno | if it arrives | >= 80 %, else "provisional" |

All judged targets must pass for a PASS. If any fails, Step 2 is not adopted and Step 1 stays the reference.

## Reported, not judged
Step 1 (0.44 / 0.11) on the same sets; A split by fire and smoke; F1; classifier accuracy and per-class recall on validation crops;
alarms on B3 (the plate frame 803445 in particular) and on the v4 fresh 250; recall by distance to training on validation
(near-copy / same video / unseen scene); a random sample of alarm crops; counts of every crop source.

## Known weaknesses, stated now
B4 is 250 frames, so one frame decides it; C has 78 images; A, N and C were seen by earlier versions (never used to train or choose; aggregate
box metrics of Step 1 on the D-Fire test were looked at); "same camera" is a 72-bit proxy; negatives are Bengaluru-only and D-Fire; other
cities, night and fog stay unmeasured; the classifier adds a second model to deploy; the near-copy filter and the 0.05 candidate floor are
conventions, not tuned values.

## If it fails
Do not retune on test. Options: more screened negatives, a look-alike class in the detector (Step 3), or the temporal layer; decided from
validation numbers only, with new locked targets and a fresh test set.
