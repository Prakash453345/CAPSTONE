# Targets: lane-aware preemption phase (written 2026-11-12T04:31Z, before any held-out run)

Change: when choosing the preemption phase, prefer a phase that protects the EV's movement **and** shows green to every other movement leaving the EV's lane (`protected_phase_for(..., lane_mates)`, `CorridorEngine(lane_mates=...)`). Off by default.

Found on training seeds 101-110 (dev). Dev result: reactive -63 s / 4 EVs, corridor -42 s; person-delay -2.7 % / -4.7 %.

Held-out: seeds **500-519** (never used), Vijayawada corridor, medium demand, current CC-A-CAMP inputs (`m8_harness.ccacamp_inputs("medium")`), the unchanged benchmark (`m7_corridor_benchmark.run_one`, via `m7_corridor_why.py`).
Arms: reactive, reactive_lane, corridor, corridor_lane. Statistic: per-seed % difference of total EV travel time (4 EVs), mean and 95 % bootstrap CI (10,000 resamples, fixed seed 0).

| id | comparison | pass if |
|---|---|---|
| H1 | reactive_lane vs reactive, EV travel time | mean <= -3 % and CI upper < 0 |
| H2 | corridor_lane vs corridor, EV travel time | mean <= -3 % and CI upper < 0 |
| H3 | reactive_lane vs reactive, cross-street person-delay | CI upper <= +3 % |
| H4 | corridor_lane vs corridor, person-delay | CI upper <= +3 % |
| H5 | _lane arms | 0 interlock violations, all EVs complete |
| D1 | corridor_lane vs reactive_lane (descriptive, no target) | reported as is |

No change to code or targets after the held-out run starts. Failures are reported as failures.
