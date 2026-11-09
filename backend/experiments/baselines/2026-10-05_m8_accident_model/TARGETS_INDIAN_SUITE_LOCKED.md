# Indian pole-CCTV suite — accident models V4 / V5 / V8 / V9 — targets LOCKED 2026-10-22, before any scoring of this suite

Data: `indian_cctv_pole_test_suite` (user-collected). Correction by the user, 2026-10-22, before any scoring: clips accident_27 and accident_28 contain NO accident (their 00:00 in `timeframe.xlsx` means none), although their file names say tbone / collision. They are therefore scored as accident-free clips (signal-jumping / near-miss traffic, i.e. hard negatives). Result: 27 accident clips (01-26 and 29, all with a crash time) and 13 accident-free clips (11 normal clips 49.0 min + clips 27 and 28 about 1.2 min = about 50 min; ATCC survey cameras, red-light enforcement cameras, two signal-jumping clips).
Nothing is trained or tuned. Each model is scored ONCE with the rule stored beside its weights (V4 deployed: thr 0.9, 2-of-3, K=2). V4 is the primary model (it is what the app runs).

## Crash times (fixed now)
- Main: the user's `Accidents.xlsx` (mm:ss, first listed time when several: clips 10 -> 6 s, 11 -> 8 s, 19 -> 5 s). Clip 6 has no entry there, so `timeframe.xlsx` (11 s) is used.
- Clips 21-26 and 29: `timeframe.xlsx`. Clips 27 and 28 are accident-free (see above).
- Sensitivity (reported, not judged): the same metrics with `timeframe.xlsx` times for clips 1-20 (first listed time). The two sheets differ by 1-4 s on clips 4, 8, 10, 13, 14, 17, 19 and 20 (see notebook).
- Definitions copied from the benchmark code: early = any alarming window ends BEFORE the crash time; detect = an alarming window ends in [t, t+10 s]; strict = detect and not early. Alarming window = the model's rule holds at that window (every hot window counts, not only run starts).

## Reported (per model, with 95 % intervals)
A. accident clips (n = 27, all timed): detect, early, strict, median delay.
B. the same 27 clips: any alarm anywhere.
C. 13 accident-free clips (pooled; clips 27 and 28 also listed on their own): alarm runs per camera-hour (exact Poisson CI), share of clips with an alarm, per-clip rows, 15 highest-scoring windows.
D. the sensitivity version of A.
The user's rejected WhatsApp clip and the fire clip are known failure cases, not part of any rate.

## Interpretation rules, stated before the run (V4 only; no model is adopted or dropped from this suite)
- I1: V4 false alarms on accident-free clips >= 1 run per camera-hour (point estimate) => the deployed rule is too noisy to raise unattended alerts; fix 1 (wording + severity) and a stricter rule go to the user as recommended. Below 1 => nothing is inferred (49 min cannot show safety).
- I2: V4 detect on timed clips < 50 % => Indian-CCTV recall is clearly below the 61 % geo-test figure; reported as a limit of the deployed model.
- Model comparison: a difference below 15 points on 27 clips (SE about 9) is not credited; V9 replaces V4 only through a separate locked plan.

## Known limits (state with any result)
- 27 accident clips: a detect rate has SE about 9 points. 13 accident-free clips from few cameras and about 50 minutes: the false-alarm rate is a rough order of magnitude.
- Clips are curated by the user (accidents chosen because they are clear), several are re-recorded screens, edited compilations or very low resolution; results mix model quality and footage quality.
- Possible overlap: the ACCIDENT benchmark contains non-US YouTube clips that may include some of these incidents; V4 trained on those. Cannot be checked here. V9 trained on all benchmark clips.
- Two crash-time sheets disagree on several clips; times were read by hand.
- Normal clips are traffic-survey and red-light cameras, not all like city incident cameras; no rain, fire, smoke or night crashes of note.
