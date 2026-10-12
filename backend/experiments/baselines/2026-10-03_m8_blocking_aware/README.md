# Blocking-aware signal control (2026-10-03 to 2026-10-05)

**Status: simulation result, not committed, not public.** Targets were written
before the held-out runs (`TARGETS.md`, with a dated amendment). Four of the
nine targets failed and a fifth (9) was missed as worded, on the good side; they are listed below as they came out.

## The problem

Where an approach has one lane, a vehicle waiting in the junction to turn
across oncoming traffic (a permissive turn) blocks everything behind it. The
adaptive controller (CC-A-CAMP) sees a long queue, gives that approach more
green, and the green is wasted: the turner still cannot go, because the
oncoming stream has green too. On the single-lane test grid this is what
locks the network at a flow ratio of about 0.45.

## What was built

1. **Sensing.** Each junction reports which lanes have a blocked head and what
   kind of movement blocks them (`JunctionContext.blocked_by`). In the
   simulator this comes from vehicle positions; with cameras it comes from one
   extra overview camera per junction (`cameras_box.json`).
2. **A second version of each phase ("variant").** It is the normal phase with
   the *protected* streams of the other approaches that the turner must yield
   to switched off. Everything else is shown exactly as in the normal phase, so
   no pair of greens appears that the normal phase does not already have.
3. **A rule for when to use it** (`strategies/hol_camp.py`). Only when a
   blocked head has lasted one change interval, only for single-lane
   approaches, only while the other approaches can still be served inside
   their maximum wait, and for at most twice the normal phase's maximum green
   per visit. Going in keeps the continuing greens; every way out is an
   ordinary yellow and all-red.
4. **Checks in the safety kernel**, not only in the controller: a variant that
   breaks any of the structural rules is refused (`Tier0Config.alternate_problems`,
   interlocks `RING_INTEGRITY`, `PLAN_CONTINUITY`).

Where no single-lane approach has such a stream to switch off, no variant is
built and the controller is CC-A-CAMP to the last digit.

## Held-out result (EVAL seeds 1-10, run 2, revision 6)

Person-delay of the new controller (`hol`) against CC-A-CAMP (`truth`), single-lane
3x3 grid, perfect data. Negative is better. Full tables: `python summarise.py`.

| flow ratio | CC-A-CAMP (s) | new (s) | difference, 95 % interval | better on | teleports new / old |
|---|---|---|---|---|---|
| 0.25 | 86,509 | 86,421 | +0.4 % [-7.6, +8.4] | 5/10 | 0 / 0 |
| 0.30 | 132,430 | 125,335 | -5.1 % [-10.2, +0.0] | 6/10 | 0 / 0 |
| 0.35 | 213,374 | 213,959 | +1.4 % [-10.8, +13.5] | 5/10 | 0 / 0 |
| 0.40 | 439,241 | 379,024 | **-13.1 % [-19.3, -6.8]** | 10/10 | 0 / 2 |
| 0.45 | 2,161,402 | 1,072,757 | **-46.5 % [-61.4, -31.6]** | 10/10 | 53 / 360 |
| 0.50 | 5,376,886 | 4,326,502 | -17.8 % [-36.1, +0.5] | 7/10 | 938 / 1475 |

In words: no effect while traffic is light, a clear gain once single-lane
junctions start to lock (0.40-0.45), and at 0.50 the roads are simply full and
both controllers jam.

Other networks (10 seeds each): corridor medium identical, heavy +3.9 %
[-3.3, +11.1]; Berlin identical at all three levels (no variant exists there);
Vijayawada district light identical, medium +2.6 % [-1.5, +6.7], heavy +1.7 %
[-7.7, +11.0]. Six networks with no single-lane approach: identical to the
last digit. No interlock violation in any of the 186 runs of the new controller.

Cameras in the loop (fine-tuned detector's measured errors, blocked lanes read
from the overview cameras only, 5 seeds): at 0.45 1,015,964 s against
1,999,968 s for CC-A-CAMP on perfect data and 1,246,724 s for the new
controller on perfect data, 29 teleports in 2 of the 5 runs; at 0.25 88,134 s
against 88,154 s on perfect data (CC-A-CAMP 85,551 s).

How well the overview cameras read a blocked lane (training seed 101, flow
ratio 0.50, 900 s, against the simulator's own rule; `dev/dev22_agreement_*`):
with a perfect detector, 93 % of camera reports are right within 2 s and 73 %
of blocked lane-seconds are caught; with the fine-tuned detector's measured
errors, 93 % and 61 %. The measured-error reading is broken into short pieces
(median 2 s against 5 s; 7.5 % of blockages last 5 s or more against 52 %).
The closed-loop runs above still worked with it.

## Targets

| # | target | result |
|---|---|---|
| 1 | zero interlock violations in every `hol` run | **pass** |
| 2 | significant gain at 0.35, 0.40 and 0.45 | **fail** -- no gain at 0.35; 0.40 and 0.45 met |
| 3 | at 0.45, at least 9 of 10 runs without a teleport | **fail** -- 6 of 10 (CC-A-CAMP: 1 of 10) |
| 4 | at 0.25 and 0.30 not worse | **pass** |
| 5 | significantly better than Webster at 0.25-0.45 | **fail** -- met at 0.25-0.40 (-28 to -44 %); at 0.45 -27.4 % [-58.5, +3.7] |
| 6 | other networks not significantly worse | **pass** |
| 7 | identical where no variant exists | **pass** |
| 8 | cameras at 0.45: significant gain over CC-A-CAMP, at most 1 of 5 runs with a teleport | **fail** -- gain met (-43.3 % [-80.7, -5.8], better on 5/5); 3 of 5 runs without a teleport |
| 9 | cameras within 15 % of perfect data at 0.25 and 0.45 | **not met as worded** -- 0.25: 0.0 % (met); 0.45: camera mean 18.5 % *lower* than perfect data (per seed -63 % to +37 %, so noise, not a camera advantage) |

## What each part does (0.45, 10 seeds, reported without a target)

| arm | against CC-A-CAMP | teleports |
|---|---|---|
| pricing only, no variants (`hol:price`) | +42.2 % [+0.4, +84.1] (worse) | 595 |
| full controller (`hol`) | -46.5 % [-61.4, -31.6] | 53 |
| full controller without the persistence wait (`hol:p0`) | -51.0 % [-62.3, -39.7] | 11 |

The gain comes from the variants; discounting a blocked lane's pressure alone
makes things worse. Acting without the one-interval wait did better here than
the default. The default was chosen on training seeds and is left as it is;
this is a lead for later, not a result.

## Waits past the configured maximum

The runner now counts junction-ticks at which some call had waited longer
than the junction's maximum wait. Single-lane grid: none for any controller.
Heavy demand elsewhere, where the network is jammed: corridor 4 ticks (worst
5.0 s over) against 3 (3.0 s) for CC-A-CAMP; Berlin 34 (5.5 s) for both;
district 10 (4.6 s) against 2 (0.8 s). So the wait guard added in revision 6
does not hold completely on the jammed district. It is a few seconds, the
interlock that enforces the wait bound did not fire, and it is not traced to
a cause yet.

## Limits -- read before quoting any number

- **Signal hardware.** Every approach needs a separate turn face that can stay
  permissive while its through face is red (a flashing-yellow-arrow type
  head). With one shared face the yellow trap returns. The simulator does not
  test this.
- **The gain is an upper bound.** Simulated drivers take every gap; real ones
  hesitate.
- **Second look at the held-out seeds.** Run 1 used the first version of the
  controller. Four code reviews then found signal-safety faults the simulator
  cannot show, and it was rebuilt five times on training seeds only
  (`TARGETS.md`, amendment). The safety fixes cost the gain at 0.35 (run 1:
  -13.1 %).
- One network family carries the positive result (a 3x3 single-lane grid).
  On the real-city networks tested the controller changes little.
- At 0.50 it still jams. Teleports remain at 0.45 in 4 of 10 runs.
- The camera reading of a blocked lane exists only in the simulated loop; it
  is not in the live message contract. A camera cannot tell a waiting turner
  from a vehicle stuck behind a full exit.
- Results repeat exactly only with the gate's pinned Python hash seed (the
  parent controller sums floats over sets).

## Prior art, and what may be new

The broad idea is not new: Omron JP7151529B2 (2019), the UK "early cut-off"
with call/cancel detection (TAL 1/06), SCATS sub-phases, the flashing yellow
arrow (MUTCD 2009 4D.20), max-pressure with estimated lane blockage
(Kobeissi, Li, Mahmassani, Chen, TRR 2026), Robbennolt et al. 2022. What a
search did not find in one piece: a detected blocked-head state that gates
both the pressure term and the set of candidate phases inside a max-pressure
controller, with the extra phases kept outside the ring and charged to their
base phase, under the guards above. Notes: `research_notes/.../blocking_aware_prior_art.md`.
This is research, not legal advice; a registered patent agent has to run a
professional search before any filing.

## Reproduce

`./run_eval.sh` from `itms/` (resumable), then `python summarise.py`.
Training-seed runs and scripts: `dev/`. Run 1: `results_run1/`
(`python summarise.py results_run1`).
