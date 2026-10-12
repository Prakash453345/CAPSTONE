# Free turns shown in every phase they fit (2026-10-11/12)

**Status: simulation result. Adopted in the benchmark configuration and wired
into the live service. Not committed.** Targets were written before the
held-out runs (`TARGETS.md`); all five passed.

## In one paragraph

A signal program from netconvert gives each movement one phase, so a turn
that crosses nothing in another phase (a left turn in left-hand traffic, a
right turn beside the opposite left, many U-turns) still waits on red through
it. Now every such movement is also shown green in every phase it conflicts
with nothing in, read off SUMO's own conflict matrix. The movement is *shown*
but not *owned*: the controller's pressure, demand, gap-out and Webster timing
read only the phase's own movements, as before (a movement's wait clock does
reset while it runs as an overlap, which can change a decision). On seeds
never used before, person-delay fell by 6.4 % on average over 15 light and
medium network-levels (the real Amaravati map not among them) and by 11.8 %
on average over three heavy ones, with no interlock violation and no
network-level significantly worse. Five network-levels carry the gain:
arterial_lh -17 % to -24 %, the right-hand grid with turn lanes -20 % to
-22 %, the Vijayawada corridor -17 % at medium. The other ten average +0.4 %.

## How it was found

The real Amaravati map still waited 36 s on average in light traffic. In one
diagnostic run (training seed 101) nearly all halting was at signals, and the
signal programs left many harmless turns on red. Three forms were tried on training seeds before the
one adopted (`dev/`, table in `TARGETS.md`):

- **Owned, timing worked out after** (`ovl`): Webster then split the cycle as
  if each free turn loaded every phase; the arterial's main road lost its long
  green (80 s -> 51 s at one junction) and person-delay at heavy demand rose
  70 %.
- **Owned, timing kept** (`ovl2`): every phase now carried the free turns'
  queues, so phases rarely gapped out (about 150 gap-outs per run fell to
  25-41); heavy +45 %.
- **Shown, not owned** (`ovl3`, adopted): -12 % / -30 % / -31 % on the
  arterial at light / medium / heavy.
- `ovl4` (no U-turns): +6.5 % on the real Amaravati map (not significant;
  51 of 89 overlaps there are U-turns), better than `ovl3` on the corridor at
  heavy demand, no better on the district.

## What changed

- `Phase.overlap_movements` and `Phase.shown_movements`
  (`itms_domain/signal.py`).
- `with_overlaps(cfg, exclude, owned=False)` and `turnaround_links`
  (`itms_domain/overlaps.py`); pedestrian signals are never added.
- The signal cabinet shows overlaps as protected green; I1 checks them against
  the phase; the clearance check counts them on every change; a movement's
  wait clock resets while it runs as an overlap (`interlocks.py`,
  `traci_cabinet.py`, `runner.py`).
- Default in `scripts/m8_harness.py` (`SHOWN_OVERLAPS`) and in
  `sim_service/main.py`. Gate arms: `truth:noovl` (before), `ovl`, `ovl2`,
  `ovl3`, `ovl4` (the forms tried). The blocking-aware (`hol`) arms are left
  without overlaps so their recorded results still reproduce.

## Held-out result (seeds 256-260, `python summarise.py`)

| network | level | before (s) | after (s) | change, 95 % interval | better on | mean wait before / after (s) | stops before / after | teleports before / after |
|---|---|---|---|---|---|---|---|---|
| amaravati_plan | heavy | 383,725 | 385,984 | +0.6 % [-1.7, +2.9] | 2/5 | 24.5 / 24.2 | 2.70 / 2.70 | 0 / 0 |
| amaravati_plan | light | 70,499 | 68,785 | -2.1 % [-9.5, +5.2] | 4/5 | 17.5 / 15.8 | 1.92 / 1.81 | 0 / 0 |
| amaravati_plan | medium | 166,385 | 164,615 | -0.9 % [-5.7, +3.8] | 3/5 | 20.5 / 19.5 | 2.24 / 2.16 | 0 / 0 |
| amaravati_v2 | light | 238,331 | 231,797 | -2.3 % [-12.2, +7.6] | 3/5 | 36.1 / 34.6 | 3.36 / 3.34 | 1 / 0 |
| arterial_lh | heavy | 278,743 | 210,920 | -24.3 % [-29.7, -18.8] | 5/5 | 62.2 / 43.4 | 2.26 / 2.02 | 0 / 0 |
| arterial_lh | light | 32,623 | 27,024 | -17.1 % [-22.4, -11.7] | 5/5 | 26.2 / 18.9 | 1.84 / 1.58 | 0 / 0 |
| arterial_lh | medium | 94,746 | 71,611 | -24.4 % [-25.8, -23.0] | 5/5 | 40.8 / 26.7 | 2.19 / 1.82 | 0 / 0 |
| berlin_adlershof | light | 14,862 | 14,996 | +1.0 % [-3.5, +5.4] | 4/5 | 9.3 / 9.7 | 1.09 / 1.12 | 0 / 0 |
| berlin_adlershof | medium | 38,990 | 40,410 | +3.7 % [-4.8, +12.2] | 2/5 | 13.4 / 14.6 | 1.35 / 1.37 | 0 / 0 |
| corridor | heavy | 478,703 | 423,548 | -11.7 % [-33.7, +10.3] | 4/5 | 91.4 / 75.7 | 2.82 / 2.92 | 7 / 0 |
| corridor | medium | 73,928 | 61,539 | -16.7 % [-20.1, -13.3] | 5/5 | 20.6 / 16.6 | 1.70 / 1.57 | 2 / 2 |
| grid4_rh_turns | light | 36,833 | 28,764 | -21.9 % [-23.5, -20.3] | 5/5 | 35.4 / 24.9 | 2.47 / 2.04 | 0 / 0 |
| grid4_rh_turns | medium | 112,489 | 90,177 | -19.8 % [-23.1, -16.5] | 5/5 | 57.0 / 42.5 | 2.97 / 2.62 | 0 / 0 |
| random_lh | light | 51,224 | 51,750 | +1.6 % [-9.8, +12.9] | 2/5 | 21.1 / 20.2 | 2.29 / 2.25 | 0 / 0 |
| random_lh | medium | 119,110 | 121,431 | +2.1 % [-6.9, +11.1] | 1/5 | 26.8 / 25.6 | 2.71 / 2.66 | 0 / 0 |
| spider_lh | light | 64,595 | 61,682 | -4.3 % [-12.6, +3.9] | 4/5 | 12.5 / 11.2 | 1.50 / 1.40 | 13 / 13 |
| spider_lh | medium | 145,301 | 137,936 | -4.9 % [-11.1, +1.3] | 4/5 | 16.8 / 14.6 | 1.85 / 1.72 | 41 / 42 |
| vijayawada_district | light | 76,669 | 76,737 | +0.4 % [-9.8, +10.6] | 2/5 | 15.2 / 15.0 | 1.93 / 1.90 | 0 / 0 |
| vijayawada_district | medium | 173,404 | 185,237 | +7.3 % [-12.2, +26.8] | 2/5 | 20.2 / 22.6 | 2.16 / 2.17 | 4 / 7 |

## What this does not show

- It is a change to the signal program, not to the control logic. Webster's
  fixed timing would very likely gain from the same overlaps too (not
  measured); the benchmark's Webster arm does not have them, so part of
  CC-A-CAMP's margin over Webster now comes from a better program rather than
  from adapting.
- Safety rests on SUMO's conflict matrix for each junction. Any real junction
  would need its overlaps checked by a traffic engineer: sight lines, a U-turn
  across a median, pedestrians (these scenarios have no pedestrians; only
  Berlin and Ingolstadt have crossings at all).
- The district at medium demand may be slightly worse: +7.4 % [+4.0, +10.7]
  on three training seeds (significant), +3.2 % [-17.9, +24.3] on ten more,
  +7.3 % [-12.2, +26.8] held-out. Its runs are noisy: vehicles jam at its
  unsignalised junctions with every arm.
- Berlin and the irregular net were slightly worse on the held-out seeds
  (+1.0 % to +3.7 %, none significant); the Amaravati plan grid moved -2.1 %
  to +0.6 % (training -3 % to -5 %); the real Amaravati map -2.3 % on five
  seeds after -9.8 % on three training seeds.
- **Reproducing these numbers:** since adoption, the arm `truth` includes the
  overlaps. The recorded `truth` is today's `truth:noovl` and the recorded
  `truth:ovl3` is today's `truth` (checked on arterial_lh light, seed 256:
  30,861 and 25,147). To re-run, use the arms `truth:noovl,truth:ovl3` and
  compare against `truth:noovl`.

## Files

`TARGETS.md` (targets, outcome), `run_eval.sh`, `summarise.py`, `results/`
(19 network-levels, 190 runs, `SUMMARY.md`), `dev/` (training-seed runs).
