# M8 vehicle detector trained on the FULL UVH-26 training split: targets, locked before any training or scoring (2026-10-28)

**Why.** `baselines/2026-10-28_m8_false_boxes_diagnosis.md`: at the same precision, fine-tune v3 and v2 find the same share of vehicles as IISc's
BatchNorm-repaired model (0.726 / 0.729 vs 0.729 on 4,797 untouched validation frames) and read the queue slightly worse. v2/v3 used 3,000 of
about 21,000 training frames. The goal is a model that is a better ranker, not another point on the same curve.

**What is trained (three runs, fixed now; nothing is changed after seeing validation numbers).**
All use every labelled UVH-26-MV-Train frame except a hold-out of 500 (seed 26, drawn from the training split; decides the best epoch),
all 14 UVH labels incl. 'Others' (so the 14-class IISc comparison is possible; the ITMS merge to six types is done at inference exactly as
today), frames stored at most 1,280 px wide, 640 px training, v3's image degradations (dimming, noise, blur, glare), one T4-class GPU.
| run | start | note |
|---|---|---|
| `s_iisc` | IISc YOLO11-S, BatchNorm re-estimated (as v2/v3) | same architecture as IISc; full precision; lr0 0.0005 |
| `s_coco` | stock YOLO11-S (COCO) | tests whether IISc's start helps; mixed precision; lr0 0.001 |
| `m_coco` | stock YOLO11-M (COCO) | accuracy ceiling; about 2.5x CPU time of S; mixed precision; lr0 0.001 |
Each runs for a fixed 8 h budget (Ultralytics `time=8`), best hold-out epoch kept in full precision, exported to ONNX (dynamic, 640).

**Never trained on.** The UVH-26 validation split (5,297 frames). The run re-checks that no validation file name is in the training set.
LIMIT: validation frames come from the same camera network as training frames (no camera id): in-domain, not a new city.

**Test and procedure (`scripts/m8_detector_fullval.py detect`, then `scripts/m8_detector_matched.py`).**
Frames: UNTOUCHED = 4,797 validation frames used by no earlier decision (all 5,297 minus the old 250 and the fresh 250). DEV = those 500 frames,
used only to place each model's score line. Operating point per model: the LOWEST score line in 0.50-0.85 (step 0.05) whose DEV precision is
>= 0.943 (the repaired IISc model's precision at its own 0.50). The model is then scored once on UNTOUCHED. References, same frames, same
pipeline: repaired IISc at 0.50 (found 0.729, precision 0.943, false boxes 0.53, PCU error 2.60) and v3 at its chosen line. 95 % paired image
bootstrap (2,000 resamples). 14-class: all 5,297 frames, as in the full run.

**Judged: "beats them" means P1-P4 all hold, per run.**
| # | target | pass if |
|---|---|---|
| P1 | more vehicles found at the same precision | found on UNTOUCHED >= 0.769 (repaired IISc 0.729 + 0.04) AND the lower end of the paired interval of (found - repaired IISc's found) > +0.02 |
| P2 | precision not paid for it | precision on UNTOUCHED >= 0.943 |
| P3 | queue estimate not worse | PCU error per image <= 2.60 |
| P4 | better on IISc's own 14-class metric | 13-class mAP50:95 (no 'Others', all 5,297 frames) >= 0.560 (repaired IISc 0.530 + 0.03) |
| P5 | speed (S runs only) | CPU time <= 1.25x IISc's, same machine, ONNX Runtime; the M run's time is reported, not judged |
If more than one run passes, the one with the higher P1 found is adopted; the number of candidates (3) is stated with the result. The M run
is adopted only as "GPU-class", never as the CPU default. If none passes, nothing is adopted and the write-up says which target failed.
Reported, not judged: AP50 (6-class), found as the right type per type (bicycle especially), recall by box height, false boxes by reason
(`fpdiag`), 14-class per-class table, v3 and repaired IISc at the same operating-point rule, and the training curves.

**Known limits, stated now.** Missing labels in the validation set count real vehicles as false boxes, so absolute precision is
understated for every model alike; the comparison at matched precision is the fair one. Selection among three candidates on one test set.
No new-camera test. Held-out degradations (night etc.) are not re-measured unless a candidate is a serious adoption candidate.
