# Gridlock round: v3 fresh-seed test. Targets written before any run on seeds 309-318

Written 2026-10-31 (IST), before any run on seeds 309-318 (no experiment has used them; previous tests: 279-288,
289-298, 299-308). Everything was chosen on training seeds 101-110 (`DESIGN.md`, `diag/`).

## The candidate (v3)

v2 (relax the green ceiling 8x while the junction's congestion weight < 0.3, 900 s memory) plus a network latch and a
warm-up (`DESIGN.md` section 4): no relaxation before 750 s; relaxation blocked at every signal while the most congested
signal (60 s load) is at or above 0.7, and until it has stayed below 0.7 for 1,800 s. Gate arm:

`truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3:s.ceiling_relax_hold_s=900:s.ceiling_relax_net_block=0.7:s.ceiling_relax_net_signal=max:s.ceiling_relax_net_halflife_s=60:s.ceiling_relax_net_release_s=1800:s.ceiling_relax_warmup_s=750`

Checksums: `FROZEN.txt`. Design check on training seeds 101-103: `diag/DESIGN_CHECK.md`.

## Setup

8 networks x light/medium/heavy x seeds 309-318, ITE all-red. Arms: `truth` (paper A), v3, `webster:pair`, `maxpressure`,
`actuated`; PressLight (paper A's models) on ingolstadt. Metric and intervals as before (per-seed % change in
person-delay, t-based 95 % interval; pooled = t interval across the 24 network-levels).

## Targets (P1-P7 are the bars of the two earlier tests, unchanged; P8 tests the design property)

| # | target | pass if |
|---|---|---|
| P1 | safety | 0 interlock violations in every v3 run |
| P2 | v3 vs paper A's controller | pooled % change below 0 with the interval entirely below 0; significantly better on >= 8/24; significantly worse on <= 2/24 |
| P3 | jams | on no network-level does v3 teleport significantly more than paper A's controller |
| P4 | v3 vs Webster | better >= 19/24, worse <= 1/24 |
| P5 | v3 vs max-pressure | better >= 16/24, worse <= 3/24 |
| P6 | v3 vs actuated | better >= 16/24, worse <= 3/24 |
| P7 | worst-case wait | v3's p95 wait significantly higher than paper A's on <= 2/24 |
| P8 | heavy cells unchanged | on the heavy cells of narrow, ingolstadt, vijayawada, berlin and amaravati, v3's person-delay equals paper A's exactly on >= 45 of 50 runs |

Adoption rule (unchanged): if P2 and P3 pass, v3 becomes the default controller. Otherwise it is reported as a tested
variant and paper A's controller stays the default. No further variant is tested on seeds 309-318.

Expected and stated now:
- Heavy demand on arterial, grid4 and random also latches, so v2's small heavy gains there are given up (about 0 %).
- Amaravati light/medium: one junction saturates late in the run (616-945 s on training seeds), so part of the gain
  there is lost.
- Narrow medium latches (it gridlocks), so it should equal paper A.
- P6 (actuated) is likely to fail again: actuated still wins heavy demand on grid4, and v3 does not change heavy demand.
