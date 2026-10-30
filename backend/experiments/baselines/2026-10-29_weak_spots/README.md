# Weak-spots round (2026-10-28/29): congestion-adaptive green ceiling

**Status: simulation results (SUMO 1.27.1, ITE all-red). Targets written before the fresh-seed run (`TARGETS.md`).
5 of 7 targets pass; N2 (the adoption target) fails narrowly, so by the rule written in advance the change is NOT made
the default. Not committed.** Tables and verdicts: `results/VERDICTS.md` (`verdicts.py`).

## What was tried (training seeds 101-103, `dev/`)

Paper A left four weak spots: the green ceiling hurt under the ITE all-red, losses to actuated at heavy demand,
losses to max-pressure at light demand on two networks, and more teleports than Webster on two cells.

- **Ceiling sweep** (`dev/ceil_*`): a looser fixed ceiling cut light-demand delay 10-34 % but made the networks that
  jam much worse at heavy demand (no ceiling: vijayawada heavy +67 %, ingolstadt heavy +69 %).
- **Switching cost** (`dev/sw_*`): at heavy demand 86 % of phase changes were pressure switches. kappa_switch 1:
  -3.7 % heavy / -4.8 % medium on 4 networks, random_lh medium +12.9 %. Not taken.
- **Congestion-adaptive ceiling** (`dev/relax_*`, `dev/combo_*`): ceiling relaxed only while the junction's
  congestion weight is low. Chosen: relax 8x below 0.3 (-8.4 % mean over 21 training cells, the only candidate that
  did not make vijayawada heavy worse). Combined with kappa_switch 1 it made vijayawada heavy +45 %; dropped.
- Diagnosis of heavy demand vs actuated (grid4 heavy): clearance share, wasted green and blocked green are the same
  for both (40 % / 23 % / 0 %); the cause is not identified.

Code: `AcampConfig.ceiling_relax_factor` / `ceiling_relax_below` (off by default), 207 tests pass.

## Fresh-seed test (seeds 289-298, 8 networks x 3 levels, 10 seeds; 1,200 runs + RL)

Arms: `truth` (paper A's controller), new (`truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3`),
Webster on the paired layout, max-pressure, SUMO actuated; PressLight on ingolstadt. Run on Michael's Mac (amaravati
light), Preethi's Mac (amaravati heavy, vijayawada, berlin) and the cloud workspace (the rest).

| # | target | result | verdict |
|---|---|---|---|
| N1 | 0 interlock violations | 0 in all 240 new runs (0 for every controller) | pass |
| N2 | vs paper A: pooled below 0 with interval below 0; better >= 8/24; worse <= 2/24 | pooled -5.0 % [-11.1, +1.2]; better 13/24; worse 0/24 | **fail** (interval crosses 0) |
| N3 | no cell with significantly more teleports than paper A | none | pass |
| N4 | vs Webster: better >= 19/24, worse <= 1/24 | 19 / 1 (amaravati heavy) | pass |
| N5 | vs max-pressure: better >= 16/24, worse <= 3/24 | 19 / 1 (ingolstadt heavy) | pass (paper A: fail, 15/4) |
| N6 | vs actuated: better >= 16/24, worse <= 3/24 | 15 / 4 | fail (paper A: 14/5) |
| N7 | p95 wait worse than paper A on <= 2/24 | 1/24 (amaravati light) | pass |

Why N2 fails: on light and medium demand the new ceiling is better on 13 of 16 cells (-3 to -24 %), worse on none.
The pooled interval is widened by the heavy-demand cells, where every controller jams and the new one is worse in
point estimate though not significantly: berlin heavy +45.3 % [-6.4, +96.9] (teleports 4,098 vs 2,989), vijayawada
heavy +17.8 % [-1.8, +37.3] (714 vs 544), ingolstadt heavy +12.6 % (n.s.). So the relaxed ceiling still switches on at
some junctions under heavy demand (the congestion weight is per junction and smoothed), and that costs where the
network jams.

Against the rivals the new controller is clearly stronger than paper A's: max-pressure losses fell from 4 to 1 and
wins rose from 15 to 19; actuated losses from 5 to 4 (amaravati heavy, grid4 medium and heavy, vijayawada heavy).
PressLight, ingolstadt: new is -12.9 % [-16.6, -9.2] at light (paper A: -3.8 %); at medium and heavy PressLight leaves
798 and 1,690 vehicles unfinished over 10 seeds (new: 0), so its lower delay there is not a valid comparison.

## What this means

- By the rule written before the run, the adaptive ceiling is **not adopted** as the default.
- It can be reported as a tested variant: a clear gain at light and medium demand, no safety cost, a possible cost
  at heavy demand on jamming networks.
- The next step, if pursued: switch the relaxation off by a network- or corridor-level congestion signal (or a
  per-junction one with a longer memory), develop on training seeds, and test again on fresh seeds 299+.

## Files
`TARGETS.md`, `FROZEN.txt`, `verdicts.py`, `run_final_cloud.sh`, `run_amaravati_medium_cloud.sh`, `results/`
(`final_*_ite.json`, `rl_ingolstadt_ite.json`, logs, `VERDICTS.md`), `dev/` (training-seed sweeps and scripts).
