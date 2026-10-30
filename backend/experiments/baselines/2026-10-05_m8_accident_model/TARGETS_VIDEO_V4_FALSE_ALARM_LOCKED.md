# V4 false-alarm + parity check — rules fixed BEFORE the run (2026-10-14)

Model under test: the deployed bundle (`itms_accident_v4.pt/.json`, geo-aware, thr 0.9, 2-of-3). Nothing is retrained or re-tuned.
Data: the geo-aware TEST split (1,573 clips, held out for this model). Same weights, same rule, a new statistic -- no threshold or rule
is changed on the basis of this run.

## A. Parity (does the app's inference code give the notebook's scores?)
20 geo-test clips (seed 0). For each, window scores from the notebook path (`V4.clip_probs` on the cache) vs the deployed
`VideoAccidentModel.observe` fed the same 4-fps frames of the raw video.
- PASS if |score difference| <= 0.05 on >= 95 % of windows AND the alarm decision (rule applied to each path) is identical on >= 19 of 20 clips.
- FAIL otherwise: the deployed pre-processing is wrong somewhere; fix before any demo. Weights rounding (fp16 -> fp32) is the same in both paths, so it is not tested here.

## B. False alarms on normal traffic -- a PROXY (diagnostic, no pass/fail)
Normal footage = the part of each test clip before the impact (windows ending at or before impact - 1.0 s). An alarm RUN there is a false alarm
(an alarm run = the rule first holding; a continuing run counts once). Report: exposure hours, alarm runs, runs per camera-hour with an exact
Poisson 95 % CI, the share of clips with any alarm before impact (should match B2's 5.2 % to within 0.5 pt, else the two calculations differ -- say so).
What this cannot show, stated in advance: pre-impact segments are short and cut from clips chosen because a crash follows (possible precursors,
near-misses); they are mostly US; they are not hours of a junction camera on an ordinary day. The number is a proxy and a lower-quality one than a
real normal-footage test.
