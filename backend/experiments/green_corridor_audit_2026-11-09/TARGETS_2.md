# Targets, round 2 — written 2026-11-12 BEFORE any reactive/queue run

Question: does the corridor beat plain reactive preemption (EV links green once the EV is within 150 m)?
Round 1 compared the corridor to NO preemption, which proves nothing about reactive. The 14 Oct M7 tests found corridor == reactive.

Arms (same routing, same signals, same EV trips; only the preemption trigger differs):
- reactive: hold the EV's phase once the EV is within 150 m of the stop line
- full (current, 260 m): same rule, 260 m
- queue (new): 150 m, widened by the queue standing on the approach road: lookahead = clamp(12 m/s * (5 s + 2 s * halted cars), 150, 450 m)

Held-out: seeds 11-19 (new O-D pairs; round 1 used seeds 1-9, no tuning on 11-19), light and medium, 4 EVs per run.
Metrics: paired % EV travel-time change (bootstrap 95 % CI, completed pairs + DNF-censored), stop-at-signal seconds, longest red, conflicts, collisions.

Pass:
- Q1 medium: queue vs reactive, mean <= -3 % and CI upper < 0
- Q2 light: queue vs reactive, CI upper <= +3 %
- Q3 longest red, queue <= 1.3 x reactive (light and medium)
- Q4 0 conflicting greens, 0 skipped yellows, 0 collisions
- Q5 (report only): full(260 m) vs reactive
If Q1 fails the honest statement is "the corridor is reactive preemption; it adds nothing over it", and that goes in the report.

## Round 2 result (held-out seeds 11-19), written before round 3
- queue(150 m base) vs reactive: 0.0 % light, +0.1 % medium -> Q1 FAIL, the queue term did nothing at that base.
- full (fixed 260 m) vs reactive: light -1.6 % [-4.0, +0.6], medium -3.3 % [-6.5, 0.0] (censored -3.7 [-7.1, -0.6]); signal-stop time medium 287 s vs 779 s. So the gain comes from looking further ahead, not from the corridor plan.

## Round 3 (dev seeds 1-9 only, then ONE confirmation on 11-19)
Candidates: la400 (fixed 400 m), q260 (260 m + queue widening, cap 450 m). Reference on dev: full (260 m, already run on seeds 1-9).
Adopt a candidate only if on dev at medium its mean EV travel time is >= 2 % better than full(260) with no worse longest red than 1.3x. Otherwise keep 260.
Confirmation on 11-19 of the adopted one: vs reactive medium mean <= -3 % and CI upper < 0; vs full, CI upper < +3 %; 0 conflicts/collisions.
