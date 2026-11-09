# Heavy-demand round (2026-11-06): diagnosis, one designed change, design check

Step 4 of the plan: the heavy-demand loss to SUMO actuated, and the vijayawada medium weak spot. Training seeds only
(101-110). Seeds 309-318 are used; the next fresh test uses 319+.

## 1. The problem

v3 (default since 2026-10-31) behaves exactly like paper A at heavy demand. There, actuated was better on the fresh
seeds on grid4 (+20.0 %), random (+8.2 %) and amaravati (+17.6 %). grid4 and random do not gridlock (0 teleports), so
this is a systematic loss, not chaos.

## 2. Diagnosis (grid4 heavy, seed 101; `diag/trace_switch.py`, `diag/t_*.json`)

| | person-delay | stops/veh | greens | mean green (s) | vehicles moving within 60 m when a green ends | queued vehicles left when a green ends |
|---|---|---|---|---|---|---|
| paper A / v3 | 194,570 | 3.31 | 1,852 | 10.4 | 499 | 494 |
| actuated | 159,238 | 2.88 | 2,119 | 9.3 | 194 | 476 |

- Not green length, clearance or junction count: actuated has *shorter* greens and more switches; same yellow 3.5 s and
  all-red 2.5 s; every junction is two-phase in both.
- Not one bad junction: halted vehicle-seconds are 15-25 % higher at every one of the 16 junctions (73,050 vs 59,082).
- The difference is *when* a green ends: our controller ends a green with vehicles about to cross 2.5x as often.
  At a pressure switch the current phase's queue is usually empty (1,257 of 1,591), and the approaching vehicles count
  only `eta_arrival` = 0.5 each over an 8 s horizon, so a few queued vehicles on red outweigh a platoon 1-2 s from the
  stop line. Those vehicles then stop and wait a full red. Actuated extends while a vehicle is within its passage time.
- Probes (diagnosis only, not candidates): `eta_arrival` 1.0 gives 176,677 (-9 %), stops 2.87; `kappa_switch` 1 gives
  173,163 (-11 %; earlier rejected for random medium +12.9 %). Both act on the whole 8 s horizon, so they also hold
  greens for vehicles still far away (mean green 12.8-15.4 s).
- random heavy (seed 101): only +3 % vs actuated on this seed; ours leaves more queued vehicles at the end of greens
  (1,344 vs 939). arterial heavy: ours is better than actuated. So the cut-off signature is clearest on grid4.

## 3. Literature

- Vehicle-actuated control extends a green while vehicles arrive within the passage time (unit extension, typically
  2-3 s) and ends it on a gap (FHWA Signal Timing Manual, 2nd ed., 2015, ch. 5).
- Miller (1963), "A computer control system for traffic networks" (2nd Int. Symp. on the Theory of Traffic Flow): extend
  the green only while the delay saved to approaching vehicles exceeds the delay imposed on vehicles waiting on red.
- MOVA (Vincent & Peirce 1988, TRRL Research Report 170) makes the same benefit-cost extension decision from detectors.
- Switch-over loss in pressure-based control: Hsieh et al. 2017 (switch bias); Levin, Hu & Odell 2020 (cyclic max-pressure).

## 4. Design: imminent-arrival extension (Miller test)

New measurement `imminent_pcu`: PCU of moving vehicles that reach the stop line within 3 s (one passage time; the same
time-to-stopline test as `approaching_pcu`, shorter horizon). Before a pressure switch, while the green is below its
ceiling and the forced-switch envelope has not fired:

    extend if  n_imminent x (lost time + next phase's minimum green)  >  queue on red x 3 s

Left side: what switching now costs the vehicles about to cross (each waits at least a clearance plus the next green).
Right side: what extending one passage time costs the vehicles waiting. No tuned parameter: 3 s is the standard
passage time; lost time and minimum green are the junction's own. `AcampConfig.imminent_extension` (off by default),
`imminent_only_loaded` (only while the network latch is engaged).

Check of the code: with the extension off, grid4 heavy seed 101 is identical to before (194,570.34); with it on,
170,295 (-12.5 %), stops 2.93 (actuated 2.88), 1,838 extensions.

## 5. Design check on training seeds 101-105 (rule written before the check)

Arms: v3 (default), v3 + extension at all levels (`E-all`), v3 + extension only when latched (`E-loaded`). 8 networks x
3 levels x 5 seeds. % change in person-delay vs v3.

- C1 (heavy gain where it does not gridlock): on grid4, random and arterial heavy, the mean % change is below 0 on each,
  and below -5 % pooled over the three.
- C2 (no harm at light/medium): on no light or medium cell is the mean % change above +3 %.
- C3 (gridlocking heavy cells; chaotic, so judged on totals): over narrow, ingolstadt, vijayawada, berlin and amaravati
  heavy (25 runs), total teleports at most 10 % above v3's, and mean % change not above +10 %.
- Selection: `E-all` if it passes C1-C3; else `E-loaded` if it passes C1-C3; else the change is not frozen and the round
  is reported as diagnosis only.

Vijayawada medium (separate): v3 vs paper A on training seeds 104-110 to find a seed with the fresh-seed failure.
