# Facing approaches share a green (2026-10-13)

**Status: simulation result. Adopted in the benchmark configuration and the
live service. Not committed.** Targets were written before the held-out runs
(`TARGETS.md`); all three passed.

## In one paragraph

The check-up of 2026-10-13 found every signal spending 22-38 % of its time in
yellow and all-red. On two networks every phase served a single approach
("split" phasing), so a four-way junction needed four changes per cycle. The
system now rebuilds such a junction from its own geometry and conflict map:
approaches that face each other share a phase, straight-ahead traffic and
turns that cross nothing run protected, and the turn that crosses the
oncoming stream runs on green but gives way. On seeds never used before,
person-delay fell by 23-30 % on arterial_lh and 31-42 % on the right-hand
turn-lane grid, at every demand level tested, on every seed, with no interlock
violation, no collision and no teleport. Other networks are not split-phased
and are unchanged.

## Held-out result (seeds 269-273)

| network | level | before (s) | after (s) | change, 95 % interval | better on | mean wait before / after (s) | stops before / after | teleports before / after |
|---|---|---|---|---|---|---|---|---|
| arterial_lh | heavy | 209,725 | 146,882 | -30.0 % [-37.9, -22.0] | 5/5 | 43.3 / 21.5 | 2.07 / 1.98 | 0 / 0 |
| arterial_lh | light | 28,662 | 21,874 | -23.2 % [-32.7, -13.7] | 5/5 | 19.6 / 10.1 | 1.63 / 1.22 | 0 / 0 |
| arterial_lh | medium | 71,974 | 52,707 | -26.6 % [-31.9, -21.3] | 5/5 | 26.1 / 12.9 | 1.83 / 1.48 | 0 / 0 |
| grid4_rh_turns | light | 29,651 | 20,573 | -30.6 % [-33.3, -27.9] | 5/5 | 26.1 / 14.6 | 2.10 / 1.69 | 0 / 0 |
| grid4_rh_turns | medium | 90,124 | 52,582 | -41.6 % [-43.9, -39.4] | 5/5 | 42.6 / 18.7 | 2.58 / 2.11 | 0 / 0 |

## How much of it is the layout, and how much the controller

Training seeds 101-103 (`dev/`), person-delay:

| network | level | Webster | Webster, paired | CC-A-CAMP before | CC-A-CAMP, paired |
|---|---|---|---|---|---|
| arterial_lh | light | 78,126 | 40,332 | 30,695 | 23,789 |
| arterial_lh | medium | 172,060 | 92,679 | 69,819 | 51,284 |
| arterial_lh | heavy | 595,750 | 214,896 | 204,067 | 146,573 |
| grid4_rh_turns | light | 60,389 | 35,738 | 29,593 | 19,854 |
| grid4_rh_turns | medium | 148,045 | 79,199 | 90,012 | 52,061 |

The paired layout helps fixed timing as much as it helps CC-A-CAMP or more:
it is a better signal program, not a smarter controller. Compared fairly
(both on the paired phases), CC-A-CAMP still has 32-45 % less delay than
Webster. On the turn-lane grid at medium demand the layout mattered more than
the controller: Webster on paired phases beat CC-A-CAMP on the old ones.

## What changed

- `itms_domain/phase_layout.py`: `net_links` (link approach, turn and approach
  heading from the SUMO network), `paired_layout(cfg, links, heading,
  lefthand, turn_phases=False)`. Five tests.
- `scripts/m8_harness.py`: `PHASE_LAYOUT = "pair"`, applied before Webster's
  greens and the ceilings; `hol` arms keep the old phases. Gate arms
  `truth:nopair`, `truth:pairt`, `webster:pair`.
- `sim_service/main.py` applies it to the live service's junctions.

## What this does not show

- A permissive turn is safe only if drivers really give way; SUMO's drivers
  always do. At a real junction the choice between permissive and protected
  turns depends on turning and oncoming volumes, sight lines and pedestrians,
  and is a traffic engineer's to make. A layout with protected-turn phases
  added (`pairt`) was tried and was worse in simulation.
- Only two of the test networks are split-phased; the others were already
  grouped and are unchanged. Many real Indian junctions are run split-phased,
  which is where this matters.
- Pedestrian signals: junctions with them are left alone.

## Files

`TARGETS.md`, `run_eval.sh`, `summarise.py`, `results/` (`SUMMARY.md`),
`dev/` (training-seed runs, including the Webster comparison).
