# Accident pipeline Stage A (detector + tracker + motion triggers) — targets LOCKED 2026-10-10, before the run

Component under test: a trigger that uses only vehicle tracks (no learned accident model). It is the first stage of
detect/track -> trigger -> short-clip confirmer -> persistence. Its recall caps the whole pipeline, so it is judged alone.

Fixed before the run: YOLO11-S (COCO weights) on cars/trucks/buses/motorcycles/bicycles, imgsz 960, ByteTrack, ~10 fps.
Triggers: T1 abrupt stop (a track's speed in body-lengths/s falls from >= v_hi to <= v_lo); T2 contact then stop
(two boxes overlap by IoU >= tau, one was moving >= v_hi in the 1.5 s before, all present tracks <= v_lo for 0.5-2 s after).
v_hi, v_lo, tau chosen from a fixed grid on VALIDATION clips (20 % of each split's train clips); frozen; the benchmark's test
splits (in-distribution 1,520 clips, geo-aware 1,573) are scored once. Impact time = `accident_time` in metadata-real.csv.

| # | Judged target (in-distribution test) | Bar |
|---|---|---|
| SA1 | trigger within 10 s after impact (any location) | >= 80 % of clips |
| SA2 | trigger BEFORE impact (any location) | <= 40 % of clips (Stage B must take this to <= 5 %) |
| SA3 | geo-aware test: same two, SA1 / SA2 | >= 70 % / <= 45 % |

Reported, not judged: location-matched recall (trigger inside the annotated crash box, grown 2x); tracker coverage (a tracked
vehicle inside the annotated box within 1 s of impact); triggers per hour of pre-impact footage; delay; breakdowns by day/night,
quality, weather, scene, crash type; each trigger alone.

Stage A passing only lets Stage B (confirmer) be built. The final B1-B5 targets in TARGETS_LOCKED.md are unchanged.
Limits: COCO detector, not the Indian-road model; ~80 % of clips are US; no long normal-only footage, so no false alarms per camera-day.
