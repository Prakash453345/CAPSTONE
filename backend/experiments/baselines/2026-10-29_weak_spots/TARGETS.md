# Weak-spots round: final test. Targets written before any run on seeds 289-298

Written 2026-10-29 (IST), before any run on seeds 289-298, which no experiment in this project has used (paper A used
279-288). Everything below was chosen on training seeds 101-103 (`dev/`); nothing is tuned on 289-298.

## The candidate

CC-A-CAMP of paper A (`truth`, frozen 2026-10-28) plus one change: a **congestion-adaptive green ceiling**. While a
junction's congestion weight (the Hill curve that already gates the switching cost; ~0.01 at light, ~0.9 at heavy) is
below 0.3, the green ceiling is 8x its configured value (effectively no ceiling); above it, the 1.25x Webster ceiling
with the 20 s floor applies as before. Gate arm: `truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3`
("new" below). Code: `AcampConfig.ceiling_relax_factor/ceiling_relax_below` (off by default). Checksums: `FROZEN.txt`.

How it was chosen (training seeds 101-103, 7 networks x 3 levels, % person-delay vs `truth`, `dev/`):
| candidate | mean over 21 cells | worst cell |
|---|---|---|
| no ceiling at all (c10) | +1.1 % (14 cells) | vijayawada heavy +67 %, ingolstadt heavy +69 % |
| relax below 0.5, factor 8 | -8.9 % | narrow_lh medium +9.7 %, vijayawada medium +6.3 % |
| **relax below 0.3, factor 8 (chosen)** | **-8.4 %** | narrow_lh medium +8.9 %, vijayawada medium +3.1 % |
| relax below 0.3 + kappa_switch 1 | -10.7 % (15 cells) | vijayawada heavy +45.3 %, random_lh medium +10.0 % |
Also tried and not taken: higher switching cost alone (kappa_switch 1: -4.8 % medium / -3.7 % heavy on 4 networks,
random_lh medium +12.9 %; lost_time_weight 3: ingolstadt heavy +100 %). The chosen one is the only candidate that did
not make vijayawada heavy worse.

## Setup

8 networks (as paper A) x light/medium/heavy x seeds 289-298, ITE all-red. Arms: `truth` (paper A's controller),
new, `webster:pair`, `maxpressure`, `actuated`; PressLight (paper A's models) on ingolstadt. Metric and intervals as
paper A (per-seed % change in person-delay, t-based 95 % interval; pooled = t interval across cells).

## Targets

| # | target | pass if |
|---|---|---|
| N1 | safety | 0 interlock violations in every new run |
| N2 | new vs paper A's controller | pooled % change below 0 with the interval entirely below 0; significantly better on >= 8/24; significantly worse on <= 2/24 |
| N3 | jams | on no network-level does new teleport significantly more than paper A's controller |
| N4 | new vs Webster | significantly better on >= 19/24, worse on <= 1/24 |
| N5 | new vs max-pressure | significantly better on >= 16/24, worse on <= 3/24 (paper A's M1 bar, failed at 15/4) |
| N6 | new vs actuated | significantly better on >= 16/24, worse on <= 3/24 (paper A's A1 bar, failed at 14/5) |
| N7 | worst-case wait | new's p95 wait significantly higher than paper A's controller on <= 2/24 |

Expected and stated now: narrow_lh medium may be worse (+9 % on training seeds); heavy demand against actuated is not
addressed by this change (training: actuated -18 % grid4 heavy, -28 % vijayawada heavy against both controllers).
If N2 and N3 pass, the adaptive ceiling becomes the default. If N2 passes and N3 fails, it is not adopted.
