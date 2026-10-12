# Blocking-aware controller: targets set before the held-out runs

Written 2026-10-03T19:10Z (2026-10-04 00:40 IST), before any EVAL-seed (1-10)
run of the blocking-aware controller (`hol`, `strategies/hol_camp.py`) on any
network. Everything it was built and chosen on is TRAIN seeds 101-110
(`dev/`); the choices are listed at the end. The only EVAL-seed runs made
during this work were Webster and CC-A-CAMP on the single-lane grid, light,
seed 1, to check that the unchanged controllers still reproduce their stored
numbers (they did, to the digit).

All runs with the gate's pinned hash seed (see `scripts/m8_closed_loop_gate.py`:
a run's result depended on Python's string-hash seed until 2026-10-04), so
CC-A-CAMP and Webster are re-run here rather than read from older baselines.

## 1. The single-lane grid, perfect data

`narrow_lh` / `narrow_sweep` (`grid:3x3,200,1`, left-hand, India mix), busiest
junction at flow ratio 0.25 (light), 0.30, 0.35, 0.40, 0.45 and 0.50
(medium). Arms webster, truth (CC-A-CAMP), hol. EVAL seeds 1-10.

Pass:
1. Zero interlock violations in every run of `hol` (this section and all below).
2. At 0.35, 0.40 and 0.45 each: `hol` has less person-delay than CC-A-CAMP,
   paired 95 % interval excluding zero.
3. At 0.45: `hol` finishes without a teleport in at least 9 of 10 runs.
4. At 0.25 and 0.30 each: `hol` not significantly worse than CC-A-CAMP and
   its mean within +5 % of it.
5. `hol` has less person-delay than Webster, significant, at every level
   from 0.25 to 0.45.

No delay target at 0.50: both controllers lock the grid there on training
seeds (the roads fill; the lane ahead is full, not blocked by a turner).
Delay and teleports are reported.

Reported without a target: `hol:price` (pricing, no variants) and `hol:p0`
(no persistence) at 0.45, 10 seeds.

## 2. Other networks that have single-lane approaches

Variants exist at 35 of 37 junctions of `vijayawada_district`, 3 of 15 of
`berlin_adlershof`, 3 of 7 of the corridor. Arms truth, hol; light, medium,
heavy (corridor: medium, heavy); EVAL seeds 1-10.

Pass:
6. At every level of each of the three networks, `hol` is not significantly
   worse than CC-A-CAMP (paired 95 % interval on person-delay includes zero
   or lies below it).

## 3. Networks with no single-lane approach

`grid3_lh`, `arterial_lh`, `grid4_rh_turns`, `spider_lh`, `random_lh`,
`ingolstadt`: no variant is built, so the controller must be CC-A-CAMP.

Pass:
7. On each, heavy demand, EVAL seed 1: `hol`'s person-delay equals
   CC-A-CAMP's to the last digit.

## 4. Cameras in the loop

Single-lane grid with one junction-overview camera per junction added to
the planned approach cameras (`cameras_box.json`, 45 cameras). Arm
`vision:itms6_640:failsafe:hol`: the blocking-aware controller on the
fine-tuned detector's measured error model, which lanes are blocked taken
from the overview cameras only. EVAL seeds 1-5, flow ratio 0.25 and 0.45.

Pass:
8. At 0.45: less person-delay than CC-A-CAMP on perfect data, paired 95 %
   interval excluding zero; no teleport in at least 4 of 5 runs.
9. At both levels: mean person-delay within 15 % of `hol` on perfect data.

## What was chosen on training seeds, and on what

| choice | options tried | evidence (TRAIN) |
|---|---|---|
| a blockage must last one change interval before anything is done | 0, 1, 2 intervals | 1 made half the changes of 0 for the same delay; 2 let the grid lock at 0.45 (`dev/dev5_*`, `dev/dev6_*`) |
| gain a variant must show over its base phase: 10 % | 10, 50, 100 % | no difference distinguishable over 5 seeds (`dev/dev5_*`); kept the first value |
| variants only for approaches whose movements share one lane | any blocked lane; only while no other lane of the approach has a queue; single-lane only | two-lane grid, heavy: +30.3 % and +7.4 % against CC-A-CAMP for the first two, on every seed (`dev/dev7_grid3_lh`, `dev/dev9_grid3_lh`) |
| pricing only where a variant exists and only after the blockage has lasted | pricing from the first blocked second, on every lane | pricing alone was never better than CC-A-CAMP on the single-lane grid (`hol:price`, `dev/dev6_*`) and moved delay on the district without a variant being used |
| return to the base phase when its other approach is owed a green or nears its maximum wait | none (first version) | 6 and 7 max-wait interlock violations on two locked training runs (`dev/dev3_narrow`), none after |
| the simulator's blocked-lane test counts a turner whose tail has cleared the stop line | SUMO's leader query | 233 of 536 camera detections scored "false" were lanes the first test missed |
| overview camera per junction | approach cameras only | approach cameras never had the waiting vehicle in frame |

Final controller on TRAIN seeds (`dev/dev11_*`, against CC-A-CAMP in `dev/dev5_*`,
`dev/dev3_narrow`, `dev/dev7_*`): 0.25 +0.2 % [-5.4, +5.9] (10 seeds);
0.35 -13.6 % [-22.8, -4.4], 0.40 -14.8 % [-29.1, -0.5], 0.45 -66.7 %
[-82.8, -50.7] with 0 teleports against 244 (5 seeds each); 0.50 -43.8 %
[-94.8, +7.2] with 122 teleports against 459 (3 seeds). District: light
identical, medium -1.2 % [-6.4, +4.0], heavy +0.2 % [-135.9, +136.3] (3
seeds; one of the medium "differences" is the hash-seed effect above, not
the controller). Berlin identical in all 6 runs; corridor identical in 5 of
6, +4.3 % in the sixth. Cameras (`dev/dev12_*`, seeds 101-102): 0.45
780,035 and 592,505 s against 814,973 and 699,692 s on perfect data and
2,299,020 and 3,325,195 s for CC-A-CAMP; 0.25 +6.4 % and +3.9 % against
perfect data.

## Amendment, 2026-10-04T17:10Z (22:40 IST) -- written before the second held-out run

The targets above are unchanged. What changed is the controller, and the
held-out seeds have now been looked at once, so this has to be said plainly.

**Run 1 (kept in `results_run1/`)** was the first version of the controller
(revision 1). It failed target 3 (5 of 10 runs at 0.45 without a teleport);
its other numbers are in that folder. It is not the result of this baseline, because
four independent code reviews then found signal-safety faults that the
simulator cannot show, and the controller was rebuilt five times:

| rev | what the review found | what changed |
|---|---|---|
| 2 | yellow trap on entering a variant | ordinary all-red entry (lost the gain) |
| 3 | -- | variant keeps the opposing turn permissive, carried entry |
| 4 | a protected green could face a kept permissive movement that does not yield to it; crossings | a variant only removes protected streams of other approaches |
| 5 | "late release" when leaving a variant | every way out of a variant is an ordinary all-red change; `can_carry` |
| 6 | wait bound exceeded at rings of three or more phases; family ceiling not enforced; rules enforced by a string filter | wait guard, enforced family budget, kernel-checked variant rules, only a yielding blocker counts |

None of these changes was chosen by looking at held-out results; each came
from a review of the code. All tuning and checking of revisions 2-6 used
TRAIN seeds 101-110 only (`dev/dev13`-`dev/dev22`). Still, run 2 is a second
use of the same held-out seeds and a reader should weigh it as such.

Facts above that are no longer true for revision 6:
- Variants exist at 35 of 37 junctions of the district, 3 of 7 of the
  corridor, 9 of 9 of the single-lane grid and **0 of 15 of Berlin** (its
  single-lane approaches have no protected opposing stream to remove). Berlin
  therefore falls under target 7's rule in practice: `hol` must equal
  CC-A-CAMP. It stays in `run_eval.sh` under target 6 as registered.
- The "return to the base phase when owed" row is replaced by: return to the
  base phase only when the variant's own approach is empty, or its family's
  time budget (2 x the base phase's maximum green per visit) is used up.

Revision 6 on TRAIN seeds 101-110, single-lane grid, against CC-A-CAMP
(`dev/dev22`): 0.25 +0.9 % [-4.1, +5.8]; 0.35 -3.3 % [-9.4, +2.7];
0.40 -14.0 % [-21.6, -6.4]; 0.45 -59.7 % [-81.4, -38.0] with 6 teleports
against 520, 8 of 10 runs without one. No interlock violation and no wait
over its bound in any run. On this evidence **targets 2 (at 0.35) and 3 are
at risk** and are left as they were written.

Precondition that the simulator does not test: each approach needs a
separate turn signal face that can stay permissive while its through face
is red (a flashing-yellow-arrow type head). With one shared face the yellow
trap returns. The measured gain is an upper bound: simulated drivers take
every gap a real driver might hesitate at.
