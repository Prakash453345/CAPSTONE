# Rest in green as an off-peak mode (2026-10-12)

**Status: simulation result. Not adopted (one of four targets failed).
`AcampConfig.rest_in_green` stays off. Not committed.** Targets were written
before the held-out runs (`TARGETS.md`).

## In one paragraph

At its green ceiling the controller changes phase even when no other road has
anyone waiting or arriving, and pays a change interval for nothing. "Rest in
green" keeps the green instead. On top of this week's default (20 s floor,
every waiting vehicle seen, free turns shown), it was tested for light
traffic only, as an off-peak mode. On seeds never used before it cut
person-delay by 6.8 % on average over ten networks (better on 8 of 10,
significantly worse on none) and broke no interlock. But on the spider
network it raised SUMO's collision count on one lane on four of five seeds,
which failed the safety target set in advance, so it is not adopted.

## Held-out result (light demand, seeds 264-268; real map 264-266)

| network | level | before (s) | after (s) | change, 95 % interval | better on | mean wait before / after (s) | stops before / after | teleports before / after |
|---|---|---|---|---|---|---|---|---|
| amaravati_plan | light | 71,183 | 61,721 | -13.0 % [-21.8, -4.3] | 5/5 | 16.2 / 12.4 | 1.83 / 1.42 | 0 / 0 |
| amaravati_v2 | light | 229,687 | 207,742 | -9.4 % [-34.9, +16.1] | 2/3 | 33.3 / 29.5 | 3.29 / 2.33 | 0 / 1 |
| arterial_lh | light | 29,174 | 27,396 | -5.3 % [-21.4, +10.7] | 3/5 | 18.8 / 18.8 | 1.60 / 1.49 | 0 / 0 |
| berlin_adlershof | light | 15,008 | 12,733 | -15.1 % [-17.4, -12.9] | 5/5 | 9.5 / 6.7 | 1.13 / 0.81 | 0 / 0 |
| grid3_lh | light | 55,717 | 55,780 | +0.6 % [-14.7, +15.9] | 2/5 | 13.0 / 12.3 | 1.63 / 1.56 | 0 / 0 |
| grid4_rh_turns | light | 28,825 | 28,009 | -2.8 % [-4.9, -0.7] | 4/5 | 24.9 / 24.3 | 2.06 / 1.96 | 0 / 0 |
| ingolstadt | light | 6,265 | 6,038 | -3.5 % [-8.6, +1.6] | 5/5 | 8.8 / 8.5 | 0.77 / 0.70 | 0 / 0 |
| narrow_lh | light | 83,379 | 84,920 | +2.2 % [-12.7, +17.0] | 1/5 | 20.0 / 19.5 | 2.23 / 2.15 | 0 / 0 |
| random_lh | light | 53,516 | 44,088 | -17.4 % [-25.0, -9.7] | 5/5 | 20.3 / 17.4 | 2.26 / 1.77 | 0 / 0 |
| spider_lh | light | 58,186 | 56,230 | -3.2 % [-10.8, +4.4] | 3/5 | 10.8 / 9.8 | 1.37 / 1.23 | 8 / 15 |
| vijayawada_district | light | 77,353 | 69,603 | -9.9 % [-14.3, -5.6] | 5/5 | 15.3 / 12.4 | 1.94 / 1.57 | 0 / 0 |

## What was learnt

- The gain is real in light traffic and largest where side roads are mostly
  empty (random net, Berlin, the Amaravati plan grid, the Vijayawada
  district).
- In medium and heavy traffic it is not worth having: on arterial_lh it lost
  5 % at medium and 3.5 % at heavy on every training seed. Four guards were
  tried on training seeds (a cap on resting, a load threshold, "no vehicle on
  any other road", "only while the running road still has traffic"); none
  kept the light-traffic gain and removed the losses.
- The spider's extra teleports are SUMO rear-end collisions on lane A1B4,
  which happen with the controller as it is too. Before switching rest on
  anywhere, that lane needs explaining: either a defect in the generated
  network or a dilemma-zone effect of longer greens ending.

## Files

`TARGETS.md` (targets, outcome), `run_eval.sh`, `summarise.py`, `results/`
(`SUMMARY.md`), `dev/` (training-seed runs, including the guards tried).

## Correction (2026-10-13)

The collisions were not on A1B4 only: across the logs they are on all five exits of the
spider's centre junction A1 (A1B1..A1B5), which netgenerate left `unregulated` (nobody
yields). A second test on fresh seeds, with A1 signalised, passed all four targets:
`baselines/2026-10-13_rest_offpeak_v2`.
