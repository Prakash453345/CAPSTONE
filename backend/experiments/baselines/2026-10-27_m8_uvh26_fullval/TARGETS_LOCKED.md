# M8 vehicle detectors on the FULL UVH-26 validation split: targets, locked before any scoring (2026-10-27)

**Why.** Every detector number so far comes from 250 validation frames (seed 26; v3 also 250 "fresh" frames, seed 2027).
Those 250 were also used to decide adoptions (v1 rejected, v2/v3 judged). This run scores all 5,297 labelled frames of
UVH-26-Val (63,497 boxes, `UVH-26-MV-Val.json`) and adds the 14-class result for IISc's model.

**Never trained on (checked, not assumed).** Train + hold-out frame lists of fine-tune v1/v2/v3 (3,300 names, identical
for all three) share 0 names with the 5,297 validation names (checked before this file was written; the run re-checks).
IISc trained on UVH-26-Train. LIMIT: validation frames come from the same camera network as training frames (no camera id
in the labels), so this is in-domain for Bengaluru, not a new-camera test.

**Models (all 640 px, ONNX Runtime, same adapter as every earlier baseline).**
`iisc` = UVH-26-MV-YOLOv11-S.onnx as released; `iisc_bnfix` = finetune_v2/iisc_bnfix_640.onnx (BatchNorm re-estimated);
`ft_v2` = itms_six_fp32_640.onnx; `ft_v3` = itms_six_aug_640.onnx (sha256 b465ec95...). File hashes are recorded in the run.

**Protocol.**
- 6-class (ITMS classes; 'Others' = ignore region): `DetectionEval`, score line 0.5 for found / precision / false boxes /
  PCU error, AP50 from floor 0.05, NMS iou 0.6, exactly as `m8_detector_eval.py`.
- 14-class (IISc only; the ITMS fine-tunes output 6 classes and cannot be scored on 14): raw 14-class head,
  multi-label, conf 0.001, class-wise NMS iou 0.7, max 300 boxes/image (Ultralytics' validation post-processing),
  COCO evaluation (pycocotools, maxDets 300). Reported twice: 13 classes (without 'Others', as the paper does) and 14.
- Subsets: ALL 5,297; OLD250 (seed-26 sample); FRESH250 (seed-2027 sample); UNTOUCHED = ALL minus both (4,797), the
  figure that no earlier decision looked at.
- Intervals: 95 % image-level bootstrap (2,000 resamples (memory on 5,297 images); paired for model differences). Alarms and vehicles cluster by
  camera, so these understate the uncertainty; stated in the write-up.

**Judged (point estimates; nothing is tuned on this data, nothing is re-adopted from this alone).**
| # | question | pass if |
|---|---|---|
| R | does the full run reproduce earlier baselines? | on OLD250, `iisc`, `iisc_bnfix`, `ft_v2` found and precision within 0.003 of the stored 250-frame results (`uvh26_640.json`, `bnfix_640.json`, `ft_640.json`; PNG frames, same adapter) |
| F1 | was the 250-frame figure representative? | for each model, ALL value of found and of precision lies inside the 95 % interval of OLD250 (bootstrap) |
| F2 | does the v3 / v2 over IISc story hold? | the 2026-09-26 bar re-applied on ALL and on UNTOUCHED, v2 and v3 each against `iisc` and against `iisc_bnfix`: found up (interval above 0), PCU error down (interval below 0), precision >= 0.90 |
| F3 | ranking by found and by PCU error is the same on UNTOUCHED as on ALL | same order of the four models |
| P | published comparison (13 classes, `iisc`) | reported, not pass/fail: our mAP50 and mAP50:95 beside the paper's 0.4486 / 0.3391. The paper's set is a different 400-image gold test (preliminary v1); a gap is not attributable to the model. Within +-0.03 on mAP50:95 would be called consistent, anything else "not the same measurement" |
| B | what does the BatchNorm repair do on 14 classes? | reported: `iisc_bnfix` minus `iisc`, mAP50 and mAP50:95 |

A failed R means the full-set pipeline differs from the earlier one (provider, decoder, images) and every other number is
read with that caveat, not discarded silently.

**Known limits, stated now.** No camera ids; PNG frames at full 1080p resolution letterboxed to 640; fine-tune training
cameras likely overlap validation cameras; paper numbers are from a different test set; 14-class applies to IISc's
model only.
