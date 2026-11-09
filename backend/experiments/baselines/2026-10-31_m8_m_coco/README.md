# M8 vehicle detector: run 3 of 3 (`m_coco`, stock YOLO11-M trained on the full training split) on the untouched validation frames, and the final comparison (2026-10-31)

Targets: `../2026-10-28_m8_full_train/TARGETS_LOCKED.md`. Same locked procedure as runs 1 and 2, run once per candidate: score line placed on the 500 DEV frames, then scored once on the 4,797 UNTOUCHED frames; reference = BatchNorm-repaired IISc at 0.50, timed in the same Kaggle CPU run. Leak check: 0 of 21,344 training names in validation.

## m_coco against the locked targets
| | repaired IISc @0.50 | m_coco @0.60 (DEV-placed) | target | verdict |
|---|---|---|---|---|
| P1 found | 0.729 | **0.779** (+0.050, paired 95 % interval +0.047 to +0.053) | >= 0.769 and lower bound > +0.02 | pass |
| P2 precision | 0.9426 | **0.9457** (+0.0031, interval +0.0011 to +0.0051) | >= 0.943 | pass |
| P3 queue PCU error | 2.60 | **2.19** | <= 2.60 | pass |
| P4 13-class mAP50:95 (all 5,297 frames) | 0.530 | **0.631** | >= 0.560 | pass |
| P5 CPU time | 1.00 | 2.67x | S runs only; M's time is reported, not judged | not judged |
False boxes per frame 0.53 -> 0.53 (difference +0.004, interval -0.017 to +0.024: no change). AP50 (6-class) 0.790 -> 0.857; 13-class mAP50 0.640 -> 0.727. Found as the right type: car 0.794 -> 0.836, auto-rickshaw 0.767 -> 0.821, bus 0.653 -> 0.726, truck 0.646 -> 0.704, motorcycle 0.691 -> 0.743, bicycle 0.33 -> 0.595.
(The script prints `P5_cpu=FAIL` for this model; the lock exempts the M run from P5.)

## All three candidates (untouched validation frames, each at its DEV-placed line)
| model | line | found | precision | false boxes/frame | queue error | 13-class mAP50:95 | CPU vs IISc | P1 | P2 | P3 | P4 | P5 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| repaired IISc (reference) | 0.50 | 0.729 | 0.9426 | 0.53 | 2.60 | 0.530 | 1.00 | | | | | |
| s_iisc | 0.55 | 0.751 | 0.9424 | 0.55 | 2.39 | 0.577 | 0.96 | fail | fail (by 0.0006) | pass | pass | pass |
| s_coco | 0.60 | 0.755 | 0.9471 | 0.50 | 2.39 | 0.608 | 1.07 | fail (0.014 short) | pass | pass | pass | pass |
| m_coco | 0.60 | **0.779** | 0.9457 | 0.53 | **2.19** | **0.631** | 2.67 | pass | pass | pass | pass | not judged |

## Verdict, honestly
- By the lock, **m_coco beats IISc's model** on P1-P4 and is adoptable only as the GPU-class detector (it is 2.7x slower on CPU). **No small model passes**: s_coco is the closest (P1 short by 0.014), s_iisc fails P1 and P2.
- The size of the m_coco gain is large compared with the noise of the paired interval (+0.047 lower bound against a +0.02 bar), but the found-share bar was passed by 0.010 only, three candidates were scored on one test set, and the interval resamples images, not cameras. Validation shares cameras with training, so a new city is not tested. Missing labels understate precision for every model alike. False boxes per frame did not fall for m_coco (0.53): at matched precision the gain shows up as more vehicles found, not fewer false boxes.
- Deploying anything is a separate decision (CPU budget, simulated-camera error presets, wiring); nothing was changed in the service.
