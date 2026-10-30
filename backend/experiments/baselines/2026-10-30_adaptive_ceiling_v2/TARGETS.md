# Adaptive ceiling v2 (with congestion memory): targets written before any run on seeds 299-308

Written 2026-10-29 22:15 IST, before any run on seeds 299-308 (no experiment has used them; the previous test used
289-298). Everything below was chosen on training seeds 101-103 (`../2026-10-29_weak_spots/dev2/`).

## Why a second test

The 2026-10-29 fresh-seed test (`../2026-10-29_weak_spots/`) of the congestion-adaptive ceiling failed its adoption
target N2 narrowly: better than paper A's controller on 13 of 24 network-levels, worse on none, but the pooled
interval crossed zero (-5.0 % [-11.1, +1.2]) because of the heavy-demand cells on networks that jam (berlin heavy
+45 %, vijayawada heavy +18 %, both n.s.). Cause: the per-junction smoothed congestion weight dips below the threshold
for short spells under heavy demand, and the ceiling is relaxed during them.

## The candidate (v2)

As v1 (ceiling 8x while the junction's congestion weight is below 0.3) plus a **15-minute memory**: the ceiling stays
tight for 900 s after the junction was last at or above 0.3. Gate arm:
`truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3:s.ceiling_relax_hold_s=900` ("v2").
Code: `AcampConfig.ceiling_relax_hold_s` (off by default). Checksums: `FROZEN.txt`.

How it was chosen (training seeds 101-103, % person-delay vs paper A's controller):
| candidate | light/medium mean | heavy mean | vijayawada heavy | berlin heavy |
|---|---|---|---|---|
| v1 (tested 2026-10-29) | -11.8 % | -4.1 % | -4.9 % | -7.1 % |
| + memory 300 s | -12.6 % | -5.4 % | -11.6 % | -6.7 % |
| **+ memory 900 s (chosen)** | -13.0 % (7 networks) | -5.0 % | **-14.5 %** | -6.8 % |
| + memory 1800 s | -13.0 % | -4.7 % | -14.2 % | (not run) |
| + network check (<= 20 % of signals congested) | -12.6 % | -3.5 % | -4.9 % | +0.5 % |
| + network check (<= 10 %) | -12.6 % | -0.3 % | +15.3 % | +3.3 % |
900 s was not worse than v1 on any training cell; 1800 s gave the same results where both were run.

## Setup

8 networks x light/medium/heavy x seeds 299-308, ITE all-red. Arms: `truth` (paper A), v2, `webster:pair`,
`maxpressure`, `actuated`; PressLight (paper A's models) on ingolstadt. Metric and intervals as before.

## Targets (same bars as the 2026-10-29 test)

| # | target | pass if |
|---|---|---|
| M1 | safety | 0 interlock violations in every v2 run |
| M2 | v2 vs paper A's controller | pooled % change below 0 with the interval entirely below 0; significantly better on >= 8/24; significantly worse on <= 2/24 |
| M3 | jams | on no network-level does v2 teleport significantly more than paper A's controller |
| M4 | v2 vs Webster | better >= 19/24, worse <= 1/24 |
| M5 | v2 vs max-pressure | better >= 16/24, worse <= 3/24 |
| M6 | v2 vs actuated | better >= 16/24, worse <= 3/24 |
| M7 | worst-case wait | v2's p95 wait significantly higher than paper A's on <= 2/24 |

Adoption rule: if M2 and M3 pass, v2 becomes the default controller (`AcampConfig` defaults changed, tests updated).
Otherwise it is reported as a tested variant and paper A's controller stays the default. No further variant is tested
on seeds 299-308.

Expected and stated now: narrow_lh medium is unchanged by v2 on training seeds (+8.9 %, noisy); heavy demand against
actuated on grid4 is not addressed.
