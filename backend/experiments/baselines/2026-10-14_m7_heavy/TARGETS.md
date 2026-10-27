# M7 under congestion: targets set before the held-out runs

Written 2026-10-14T17:03Z (22:33 IST), before any run on seeds 284-293, which no
M7 experiment has used (M5/M8 work used 1-10, 101-140, 241-283).

## Why
The 14 Oct re-run (baselines/2026-10-14_m7_rerun) tested medium demand only: corridor and
reactive preemption were indistinguishable. On training seeds 101-105 (`dev/`, current
controller inputs as Run B) the picture splits by demand:

| corridor vs reactive (5 training seeds) | EV travel time | EV stops | person-delay |
|---|---|---|---|
| medium | +10.8 s [10, 1, 23, 36, -16] | +1.0 | +1.2 % |
| heavy | -38.8 s [-33, -25, -58, -108, +30] | -1.4 | -2.7 % |

Tried on the same seeds and dropped: claiming every junction within 300 m as well
(`corridor_union`; with the A/D terms off it equals reactive on 9 of 10 runs) and the corridor
without A(p)/D(p) (`corridor_noAD`: medium +5.0 s, heavy -31.8 s, noisier).

## Held-out run
`scripts/m7_corridor_benchmark.py` arms `reactive` and `corridor` (unchanged code), current
CC-A-CAMP inputs (`m8_harness.ccacamp_inputs`, as Run B), seeds 284-293, heavy and medium.

Pass (heavy, the claim being tested):
- **H1.** EV travel time: corridor minus reactive, paired mean, 95 % t interval entirely below 0.
- **H2.** EV stops: not significantly higher (interval not entirely above 0).
- **H3.** Cross-street person-delay: not significantly worse (paired % change interval not
  entirely above 0).
- **H4.** Zero interlock violations in every run.

Reported, no pass/fail: medium on the same seeds (expected: no difference or slightly worse).

If H1-H4 pass, M7's claim becomes "the corridor beats reactive preemption under congestion
(heavy demand); at medium demand they are equivalent". If H1 fails, M7 is "safe preemption
plus dispatch", with no advantage claimed over reactive.

## Outcome (2026-10-14T17:40Z)

Held-out, heavy, 10 paired seeds (`python summarise.py`, `results/SUMMARY.txt`):
- H1 **FAIL**: EV travel time +3.6 s [-30.8, +38.0] (corridor 1177 s vs reactive 1174 s).
- H2 pass: EV stops +1.5 [-0.2, +3.2] (more stops, not significant).
- H3 pass: cross-street person-delay -2.0 % [-9.7, +5.7].
- H4 pass: zero interlock violations.

Medium, same seeds (reported): EV +5.6 s [-1.6, +12.8], stops +0.6 [-0.1, +1.3], person-delay
+0.9 % [-6.8, +8.6]. The heavy-demand gain on training seeds 101-105 did not hold; it was noise.
**M7 is "safe preemption plus dispatch"; no advantage over reactive preemption is claimed.**
