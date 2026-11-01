# Gridlock round (2026-10-31): diagnosis first, one designed change, then one fresh test

Michael asked for a designed solution rather than trial and error. This file records the diagnosis, the literature, and
the design, written before any run of the new controller on fresh seeds. Training seeds only (101-110).

## 1. The problem

The congestion-adaptive ceiling (v1, v2) helps at light and medium demand on two fresh-seed tests but failed adoption
both times because of heavy-demand cells on networks that gridlock (berlin heavy +114 %, ingolstadt heavy +97 % on
seeds 299-308, both n.s., with per-seed swings from -84 % to +981 %).

## 2. Diagnosis (training seeds; `diag/`)

**2a. Heavy demand on these networks is chaotic: any small change flips which seeds gridlock.**
Ingolstadt heavy, seeds 101-110, paper A's controller against copies with one parameter nudged
(`diag/chaos_ingolstadt.json`, `diag/chaos2_ingolstadt.json`):

| change to paper A's controller | per-seed % person-delay vs paper A (101-110) | mean | seeds changed > 20 % |
|---|---|---|---|
| rho_jam 0.85 -> 0.851 | 0 0 0 0 0 0 0 0 -30 0 | -3 | 1/10 |
| rho_jam 0.85 -> 0.86 | 0 0 0 0 +40 -11 -8 0 -30 0 | -1 | 2/10 |
| rho_jam 0.85 -> 0.84 | -49 +1 0 0 +26 +3 -10 0 0 0 | -3 | 2/10 |
| eta_arrival 0.50 -> 0.52 | +52 +1 +1 +123 +37 +7 +18 -6 -65 -20 | +15 | 5/10 |
| v2 (adaptive ceiling) | -63 -9 +41 +250 +67 +24 -76 -1 -66 -19 | +15 | 7/10 |

A 4 % change in the weight on approaching vehicles, which should do nothing systematic, swings single seeds by +123 %
and -65 % and gives the same mean as v2. So v2's heavy result on this network cannot be told apart from the effect of
any change at all. The earlier training sweeps show the same on berlin and vijayawada (e.g. berlin heavy seed 102: ceiling
1.5x -79 %, ceiling 3x +118 %; ingolstadt seed 101: every variant -43 to -66 %, even SUMO actuated).

**2b. Where gridlock starts.** Teleports are mostly "waited too long (yield)": vehicles that need a gap in a stream
(permissive turns at signals, minor roads at priority junctions near signals) never get one, their queue spills back,
and a junction box blocks (`diag/classify_teleports.py`, `diag/hot_lanes.py`). Ingolstadt: the jam always starts at
the same place, lane gneE9_1 (9.8 m long, feeding signal 335525545), at t = 820-870 s, then the priority junction
upstream (276184048) blocks within 100 s. Whether it tips depends on exact arrival timing, which is why tiny changes flip it.

**2c. Why v2 still changes heavy runs.** Two concrete flaws, both measurable:
- The smoothed loads start at zero, so in the first minutes of every run each junction reads "quiet" and relaxes.
- The decision is per junction. In berlin heavy, v2 relaxed in about 79 % of controller decisions (48,721 of 62,018
  ticks, seed 299), because most junctions are quiet while a few areas jam.
Either is enough to change a chaotic run.

**2d. Which network signal sees heavy demand early** (`diag/trace*_*.json`, `diag/cross.py`; paper A's controller,
control unchanged, delay identical to earlier truth runs on the same seeds; training seeds 101-103, all 8 networks):
- The network *mean* of the per-junction congestion weight misses large networks where the jam is local: amaravati heavy
  never exceeds 0.17, vijayawada heavy 0.13, while arterial heavy (which never gridlocks) reaches 0.38 (trace1/2).
- The *worst* junction is junction-count independent. With the controller's 300 s load it crosses 0.7 too late
  (ingolstadt 625-747 s, vijayawada 535-801 s; trace2). With a 60 s load (about one signal cycle; trace3) it crosses 0.7 at:
  narrow heavy 92-107 s, narrow medium 168-219 s, berlin heavy 165-219 s, ingolstadt heavy 324-334 s, vijayawada heavy
  369-694 s; never in light or medium on arterial, grid4, random, ingolstadt, berlin; once in narrow light (446 s, 1 of 3
  seeds) and in vijayawada medium (561-596 s, 2 of 3 seeds, a local hotspot that also produced teleports).
  Amaravati (trace finished after the design below was written, before any check result): heavy 262-317 s; but one
  junction also saturates at light (902-945 s) and medium (616-674 s), so v3 will lose part of its amaravati gain.
  Heavy demand on the networks that do not gridlock also crosses it (arterial 534-898 s, grid4 323-349 s, random
  383-464 s), so v3 will give up v2's heavy-demand gains there; that is accepted.

## 3. Literature

- Congested urban networks are unstable; past a critical accumulation flow collapses and small disturbances decide
  whether a jam spreads (Daganzo 2007, "Urban gridlock"; Gayah, Gao & Nagle 2014, TR-B 70:255-268).
- Network flow is governed by the spatial spread of density: full links block upstream discharge (Mazloumian,
  Geroliminis & Helbing 2010).
- Perimeter (gating) control acts on a network-level state (accumulation or occupancy against the critical value of the
  network fundamental diagram) rather than junction by junction (Keyvan-Ekbatani et al. 2012).
- Capacity-aware back-pressure: pressure should account for finite link storage, or the controller can serve into full
  links and deadlock (Gregoire et al. 2015, arXiv:1309.6484).

## 4. Design (v3): decide for the network, and change nothing once the network is loaded

Principle: the adaptive ceiling is a light/medium-demand tool. When any part of the network is saturated, behave
exactly like paper A's controller everywhere, so heavy-demand cells cannot flip.

v3 = v2 (relax 8x while the junction's congestion weight < 0.3, 900 s memory) plus:
1. **Network latch on the worst junction.** Every signal posts the congestion weight of a 60 s smoothed load
   (`ceiling_relax_net_halflife_s=60`, `ceiling_relax_net_signal=max`). When the most congested signal reaches 0.7
   (`ceiling_relax_net_block=0.7`), relaxation is blocked at every signal until the worst signal has stayed below 0.7
   for 1,800 s (`ceiling_relax_net_release_s`, a peak period, so the latch does not toggle inside one).
2. **Warm-up** W: no relaxation before t = W (`ceiling_relax_warmup_s`), because the simulation starts from an empty
   network and a heavy run needs time to show it is heavy.

Choices from the measurements in 2d, not from outcomes: worst junction (the mean misses local jams); 60 s (one cycle;
300 s detects too late); 0.7 (crossed early by every gridlocking run, never by light/medium on five of the networks).

The warm-up is the one trade-off: longer W protects heavy runs that latch late (vijayawada heavy seed 103 at 694 s)
but removes relaxation from the start of light/medium runs, which last only ~2,000 s. Two values are checked,
W = 300 s and W = 750 s (above the latest crossing measured, 694 s).

## 5. Design check on training seeds 101-103 (rule written before the check)

- D1 (heavy cells unchanged): on the gridlocking cells (narrow medium/heavy, ingolstadt, vijayawada, berlin, amaravati
  heavy) v3's person-delay equals paper A's exactly on every seed.
- D2 (gains kept): on light and medium of arterial, grid4, random, ingolstadt and berlin, v3's mean % change vs paper A
  is at least 2/3 of v2's (v2 from `../2026-10-29_weak_spots/dev2`).
- Selection: the shorter warm-up that passes D1 and D2; if neither passes D1, the longer one if it passes D1 and D2;
  if neither, v3 is not frozen and the round is reported as diagnosis only.

Not addressed in this round, and stated now: heavy-demand gridlock itself (yield starvation and short-link spillback).
That needs a controller that lowers the probability of tipping, and an evaluation with many more seeds per cell,
because single heavy cells are coin flips.
