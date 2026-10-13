# Accident video model (ACCIDENT benchmark, real CCTV) — targets LOCKED 2026-10-05, before any training

Data: Picek et al., ACCIDENT benchmark (Kaggle `picekl/accident`, CC BY-NC-ND 4.0, non-commercial).
All 2,027 real clips are accidents; each has an annotated impact frame. Frames before the impact are
used as "normal traffic", frames after as "accident". Synthetic (CARLA) clips: training only, never in any test number.

Protocol: the benchmark's own splits. In-distribution: train 507 / test 1,520 clips. Geo-aware: train 454 / test 1,573.
20 % of each train split is held out as validation for choosing the threshold and persistence rule. Each test split is scored ONCE.

| # | Target | Bar |
|---|---|---|
| B1 | In-distribution: clips where the model raises an alarm within 10 s after the impact frame | >= 70 % |
| B2 | In-distribution: clips with an alarm raised BEFORE the impact frame (false alarm on normal traffic) | <= 5 % |
| B3 | Median delay, impact -> alarm | <= 5 s |
| B4 | Geo-aware split: B1 / B2 | >= 60 % / <= 8 % |
| B5 | Nothing tuned on a test split; threshold fixed on validation before the test run | |

Known limits stated up front: ~80 % of clips are US; no Indian footage is in the test, so accuracy on Indian
junction cameras is unmeasured. "Normal" is only the pre-impact stretch of accident clips (short, same cameras),
so B2 is a per-clip rate, not false alarms per hour. Output is a candidate for an operator to confirm (ADR-006).
