# Paper A: final benchmark. Targets written before any run on seeds 279-288

Written 2026-10-28 (IST), before any run on seeds 279-288, which no experiment in this project has used
(`claude/algorithm_next_prompt.md`: "next unused held-out seeds: 279 onward"). Nothing below is tuned on them.

## The frozen controller

CC-A-CAMP as the default arm `truth` of `scripts/m8_closed_loop_gate.py` on 2026-10-28: paired phases on
split-phased junctions, 1.25x Webster green ceiling with a 20 s floor, cycle supervisor, gap-out (3 s grace),
split-road sensing (via2), shown overlaps, kinematic yellow. One change since the last held-out run, a safety fix:
the I5 urgency margin (`acamp._wait_margin_s`) is now sized per junction,
`max(15 s, (phases - 1) x (min green + yellow + all-red) + 1 s)`, instead of a flat 15 s
(why: README section "All-red"). File checksums are in `FROZEN.txt`; nothing in them changes until this run ends.

## Setup

- **Networks (8):** arterial_lh, ingolstadt, narrow_lh, random_lh, grid4_rh_turns, berlin_adlershof,
  vijayawada_district, amaravati_v2. Demand: light, medium, heavy (flow ratios 0.25 / 0.5 / 1.0 at the busiest
  junction, as built by `scenarios/build_scenario.py`). 24 network-levels.
- **Seeds:** 279-288 (10) for the main table; 279-283 (5) for the ablation and camera runs.
- **All-red:** the primary results use the ITE all-red per junction (`SIGNAL_ALL_RED=ite`). Ours and Webster
  are also run on the flat 2.0 s all-red, same seeds, so both versions can be reported.
- **Controllers (ITE):** ours (`truth`); Webster on the same phase layout (`webster:pair`); plain max-pressure,
  Varaiya, 10 s slot (`maxpressure`; slot chosen on training seeds 101-102 from 5/10/20 s by mean ratio to the best
  over random_lh and grid4_rh_turns, light and heavy); SUMO's built-in actuated control on the same phases and
  clearances, max-gap 3 s, minDur = min green, maxDur 50 s (`actuated`; 50 s kept over 30 s on the same check);
  PressLight-style DQN on ingolstadt only (`scripts/paper_a_rl.py`, trained on seeds 101-108, checkpoint chosen
  on 109-110).
- **Metric:** total person-delay (occupancy-weighted time lost) per run; per seed the % change of ours against
  the other controller; mean over seeds with a t-based 95 % interval. Also reported: delay per trip, p95 wait,
  stops per vehicle, teleports, vehicles unfinished at the run cap, interlock violations.

## Targets (ITE all-red unless stated)

| # | target | pass if |
|---|---|---|
| S1 | safety, ours | 0 interlock violations in all ours runs (ITE and flat) |
| S2 | jams, ours vs Webster | on no network-level does ours teleport significantly more than Webster (95 % interval of the per-seed difference entirely above 0) |
| W1 | ours vs Webster | ours significantly lower person-delay on >= 18 of 24 network-levels |
| W2 | ours vs Webster | ours significantly higher on <= 2 of 24 |
| W3 | ITE does not erase the gain | pooled % vs Webster under ITE within 5 points of the pooled % under flat 2.0 s (same seeds) |
| M1 | ours vs max-pressure | ours significantly lower on >= 16 of 24, significantly higher on <= 3 |
| A1 | ours vs actuated | ours significantly lower on >= 16 of 24, significantly higher on <= 3 |
| P1 | worst-case waiting | ours' p95 wait significantly higher than Webster's on <= 3 of 24 |
| R1 | ours vs PressLight (ingolstadt) | ours lower on all 3 levels, at least 2 significantly (reported either way) |

Expected and stated now: narrow_lh (single-lane roads with turns) has failed before; heavy demand on
vijayawada_district has not been significant before. Both count against the targets like any other cell.

## Ablation (ITE, seeds 279-283, 7 networks without amaravati_v2: 21 network-levels)

One part off at a time, against the full controller on the same seeds. Reported, not pass/fail:
`truth:c10` (ceiling effectively removed: 10x Webster), `truth:nopair` (paired phases off), `truth:ync` (yellow
from netconvert's guess instead of the kinematic rule), `truth:f0` (20 s floor off), `truth:s.gap_out_grace_s=-1`
(gap-out off), `truth:nov` (split-road sensing off), `truth:s.cycle_supervisor=false` (the "static ceiling":
adaptive control under the network-derived ceiling, no supervisor), `truth:noovl` (shown overlaps off).
Webster on the paired layout is the "network-derived timing only, no adaptation" row.

## Lane-less Indian traffic and cameras (reported, not pass/fail)

- `arterial_lh_sublane`, `vijayawada_district_sublane` (`scenarios/make_sublane_variant.py`: SUMO sublane model,
  0.8 m resolution; two-wheelers and autos filter, arbitrary lateral position): all four controllers, seeds 279-288.
  Reported: does ours still beat each baseline, and by how much compared with lane-based runs.
- Cameras in the loop, the adopted detector (`vision:itms6_640:failsafe`), arterial_lh and random_lh, three
  levels, seeds 279-283: the cost against perfect data, and teleports at heavy demand.
