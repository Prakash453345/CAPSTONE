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

## Amendment 2, 2026-10-05T16:40Z (22:10 IST) -- written before held-out run 3

Run 2 is the result for revision 6 and stands as reported in the README. This
amendment registers a **new controller setting and a new held-out run on
seeds that have never been used** (201-220). EVAL seeds 1-10 are not used
again.

**What changed, on TRAIN seeds only** (`dev/dev23`-`dev/dev28`, TRAIN extended
from 101-110 to 101-140; none of these seeds is in any held-out set):

- The controller now acts on a blocked head at once (`min_blocked_changes`
  1 -> 0) and a visit that uses a variant may last three times the base
  phase's maximum green (`family_budget` 2 -> 3). The arm name is still `hol`;
  run 2's controller is `hol:rev6`.
- The wait guard allows for every other phase of the ring coming first at
  rings of three or more phases (it allowed for one). Two-phase rings, and so
  the whole single-lane grid, are unaffected to the last digit.
- Nothing else. The green-ceiling lead was screened and dropped: three times
  Webster's green gave -10.3 % [-14.3, -6.3] at 0.25 but nothing at 0.30-0.40
  and more teleports at 0.45 (`dev/dev23_ceil_*`).

**Why this setting.** Four settings were compared (default, p0, b3, p0:b3).
On ten seeds none could be told from the default. The rule was then written
down before the larger run: take b3 if it is not worse than the default at
0.45, else p0:b3 if it is not worse anywhere and has more runs without a
teleport, else keep the default. On 40 seeds (0.30-0.40) and 30 seeds (0.45),
paired against the default: b3 -3.5 % [-5.7, -1.4] at 0.30 and no difference
at 0.35/0.40, but 64 teleports against 32 at 0.45; p0:b3 -2.3 % [-4.7, +0.0],
+1.8 % [-2.5, +6.1], -0.7 % [-4.5, +3.2], -2.9 % [-9.7, +3.8] at
0.30/0.35/0.40/0.45 and **27 of 30 runs at 0.45 without a teleport against 19
of 30**. So p0:b3. The honest size of the change: no measurable difference in
delay, fewer lock-ups at 0.45.

p0:b3 against CC-A-CAMP on TRAIN: 0.25 -0.7 % [-7.0, +5.6] (10 seeds);
0.30 -2.8 % [-5.2, -0.5], 0.35 -5.1 % [-8.0, -2.3], 0.40 -12.9 %
[-18.1, -7.7] (40 seeds); 0.45 -62.3 % [-77.8, -46.7] (10 seeds). Cameras in
the loop at 0.45 (seeds 101, 102): 646,869 and 740,704 s against 1,033,886
and 1,042,433 s for revision 6 with cameras; at 0.25, 90,079 and 94,731 s
against 83,820 and 84,188 s on perfect data (+7.5 %, +12.5 %). Heavy
district, ten seeds: -5.9 % [-30.5, +18.7], better on 8, 500 teleports
against 601; 4 junction-ticks past the maximum wait for each controller
(worst 1.6 s against 0.8 s), none of them after a variant.

**Run 3** (`run_eval3.sh`, results in `results_run3/`): single-lane grid 0.25
to 0.45, arms truth, hol, hol:rev6, seeds 201-220; corridor and district,
truth and hol, seeds 201-210; Berlin and the six networks without variants,
heavy, seed 201; cameras at 0.45 and 0.25, seeds 201-205. No run at 0.50:
both controllers jam there and nothing in this change addresses it.

Pass:
- **A1.** Zero interlock violations in every `hol` run.
- **A2.** At 0.35, 0.40 and 0.45 each: `hol` has less person-delay than
  CC-A-CAMP, paired 95 % interval excluding zero.
- **A3.** At 0.25 and 0.30 each: `hol` not significantly worse than
  CC-A-CAMP and its mean within +3 % of it.
- **A4.** At 0.45: `hol` finishes without a teleport in at least 16 of 20
  runs.
- **A5.** Against `hol:rev6` on the same seeds: at 0.45 at least as many runs
  without a teleport; at every level not significantly worse in person-delay.
  (This is the claim of this amendment: fewer lock-ups, delay unchanged.)
- **A6.** Corridor (medium, heavy) and district (light, medium, heavy): `hol`
  not significantly worse than CC-A-CAMP.
- **A7.** Berlin and the six networks without variants: identical to
  CC-A-CAMP to the last digit.
- **A8.** Single-lane grid: no junction-tick with a call past the maximum
  wait in any `hol` run. Elsewhere the count and the worst excess are
  reported beside CC-A-CAMP's, without a target: CC-A-CAMP itself passes the
  bound by up to a few seconds on jammed networks (its 15 s margin does not
  cover a second phase coming first), and that is not changed here.
- **A9.** Cameras at 0.45: less person-delay than CC-A-CAMP on perfect data
  in 5 of 5 runs, and at most one run with a teleport. Cameras at 0.25: mean
  person-delay not more than 15 % above `hol` on perfect data. (The bar is
  target 9's of run 2. It was first written here as 10 %; the two TRAIN
  camera runs at 0.25 then came in at +7.5 % and +12.5 %, and it was put
  back to 15 % before any held-out run. Said so that it can be weighed.)

### Outcome of run 3 (2026-10-05T17:20Z)

Run on seeds 201-220, single-lane grid only, then stopped. In the records the
setting registered above as `hol` is named `hol:p0:b3:g1` (g1: the wider wait
guard), because the default was taken back to revision 6 afterwards.

- A1 pass (100 runs, no violation). A8 pass (no tick past the maximum wait).
- A2 **fail**: 0.35 -1.7 % [-7.1, +3.7]; 0.40 -12.6 % [-19.5, -5.8] and 0.45
  -59.4 % [-66.0, -52.7] met.
- A3 pass: 0.25 -2.0 % [-5.4, +1.4], 0.30 -2.3 % [-6.6, +2.0].
- A4 **fail**: 11 of 20 runs at 0.45 without a teleport (16 wanted).
- A5 **fail**: revision 6 had 13 of 20 on the same seeds. Delay against
  revision 6: +2.0 % [-1.2, +5.3], -1.0 % [-5.8, +3.9], +1.4 % [-5.1, +7.8],
  +0.7 % [-16.7, +18.2] at 0.30-0.45 and -0.8 % [-4.4, +2.7] at 0.25.
- A6, A7, A9 not run: with A4 and A5 failed the setting was not going to be
  adopted, and the remaining runs (about three hours) would have described a
  controller that is not shipped.

Decision: the default stays revision 6 (`min_blocked_changes` 1,
`family_budget` 2, the guard as in run 2). `wide_guard` stays in the code,
off.

## Amendment 3, 2026-10-05T17:15Z (22:45 IST) -- written before held-out run 4

Two leads left open by round 2, each with a reason beyond a training-seed
number. Seeds 201-210 (201-206 for cameras): run 3 used 201-220 on the
single-lane grid with perfect data only, so no run of these arms on these
networks, and no camera run on these seeds, has been seen. Controller:
revision 6 (`hol`); the two options are `hol:g1` and `...:hol:p0:b3`.

**G -- the wider wait guard (`wide_guard`).** It changes nothing at two-phase
rings. Variants exist at rings of three or more phases at four junctions of
the district and one of the corridor. Heavy demand, arms truth, hol, hol:g1.

- G1. No interlock violation in any `hol:g1` run.
- G2. In the `hol:g1` runs, no wait-overrun event (`wait_overruns`) has a
  variant among the junction's last eight phases. (`hol`'s count is reported
  beside it; if `hol` has none either, G2 says nothing and that is reported.)
- G3. `hol:g1` is not significantly worse in person-delay than `hol` and than
  CC-A-CAMP on either network (paired 95 % interval includes zero or lies
  below it).

If G1-G3 pass, `wide_guard` becomes the default.

**C -- acting at once when blocked lanes come from cameras.** The camera
reading is broken into short pieces (median 2 s against 5 s for the
simulator's rule), so a blockage rarely "lasts one change interval" as
revision 6 asks. Arms: cameras with revision 6, cameras with p0:b3; single-lane
grid, 0.45 (six seeds) and 0.25 (three seeds).

- C1. At 0.45: cameras with p0:b3 have less person-delay than cameras with
  revision 6, paired 95 % interval excluding zero.
- C2. At 0.45: no more runs with a teleport than cameras with revision 6.
- C3. At 0.25: mean person-delay within +5 % of cameras with revision 6.
- C4. No interlock violation.

If C1-C4 pass, p0:b3 becomes the setting used when the blocked-lane reading
comes from cameras (with perfect data run 3 found it no different from
revision 6). On training seeds 101, 102: 646,869 and 740,704 s against
1,033,886 and 1,042,433 s at 0.45; 90,079 and 94,731 s against 97,992 and
88,571 s at 0.25.

**D -- the district between "medium" and "heavy"** (added 2026-10-05T17:50Z,
before any run on it). Why the district shows nothing: at "heavy" its busiest
junction is at a degree of saturation of 1.0 and jams the network, while 28 of
the 35 junctions with variants are below 0.35 -- the single-lane grid's nine
are all at 0.34-0.45, the band where the variants pay. `vijayawada_district_mid`
is the same network with demand set so the busiest junction is at 0.65 and
0.80. Arms truth, hol (revision 6); seeds 201-210.

- D1. `hol` is not significantly worse than CC-A-CAMP at either level.
- D2. No interlock violation.
- Reported without a target: whether `hol` is better at either level, and how
  often variants are used. A gain here would be the first on a real street
  network; no gain means the result stays confined to evenly loaded
  single-lane grids.

**D -- a real network between "medium" and "heavy" (added 2026-10-05T17:31Z,
before any run of it).** Why the district showed nothing in runs 1 and 2: its
demand is random trips scaled until the *busiest* junction reaches a target
load, and the other junctions sit far below it. At "medium" (busiest 0.51)
the next ones are at 0.31, 0.28, 0.26; at "heavy" (busiest 1.00, which locks
the network) only seven of the 35 junctions with variants are at 0.38 or
more. On the test grid all nine junctions are at 0.34-0.45, the band where
the controller pays. So the district was tested either below the band or
inside a jam caused elsewhere. `scenarios/generated/vijayawada_district_mid`
is the same network with the busiest junction at 0.65 (`d65`) and 0.80
(`d80`). Arms truth, hol; seeds 201-210. Nothing is tuned on it.

- D1. At both levels `hol` is not significantly worse than CC-A-CAMP and has
  no interlock violation.
- D2 (the question, not a requirement): is `hol` significantly better at
  either level? Reported with how often a variant was used.

Whatever D2 shows is the answer to "does this matter on real streets with
this kind of demand", and is reported as such.

**E -- two more single-lane networks (added 2026-10-05T17:33Z, while they
were being built).** The positive result rests on one 3x3 grid. Two networks the
controller has never run on, both left-hand, one lane each way, India mix:
`narrow_grid54_lh` (`grid:5x4,150,1`, 20 junctions, shorter blocks) and
`narrow_rand_lh` (`rand:40,150,1,7`, an irregular street net, uneven junction
loads like a real one). Levels: busiest junction at 0.30, 0.40, 0.45. Arms
truth, hol; seeds 201-210. Nothing is tuned on them.

- E1. No interlock violation; at 0.30 `hol` not significantly worse.
- E2. On the regular grid: `hol` significantly better than CC-A-CAMP at 0.40
  and at 0.45 (the claim "it is not a property of one 3x3 grid").
- E3 (the question, not a requirement): the same on the irregular net, where
  only the busiest junctions are in the band.

**Cut back before any of these runs was made (2026-10-05T18:30Z), to save
computing time:** C runs on four seeds (201-204) at 0.45 instead of six, and
the 0.25 camera runs (C3) are dropped; E runs at 0.40 and 0.45 only (the
0.30 part of E1 is dropped). With four seeds C1 can only show a large effect.

### Outcome of G (2026-10-05T19:15Z) -- decided before D and E started

Heavy demand, ten fresh seeds each. G1 pass (no violation). G2 pass: with
`hol:g1` no wait overrun followed a variant visit; revision 6 had one on the
district (2.6 s). Overruns with no variant near, district: 4 for each of the
two, 2 for CC-A-CAMP (worst 1.6 s, 1.6 s, 0.8 s); corridor: one of 3.0 s,
the same for all three. G3 pass: against revision 6, +1.6 % [-0.7, +3.8]
on the district (better on 0 of 10 seeds -- a small cost that this sample
cannot confirm) and +0.7 % [-0.8, +2.2] on the corridor; against CC-A-CAMP,
+5.5 % [-4.0, +15.0] and -5.4 % [-12.0, +1.3].

So `wide_guard` is now the default (**revision 7** = revision 6 with the
wider guard; identical to revision 6 at two-phase rings). In the records of
this part revision 6 is named `hol:rev6`. **D and E, registered above with
`hol`, run with revision 7.** C is on the two-phase grid and is unaffected.

### Outcome of C, D and E (2026-10-06T06:10Z)

**C -- cameras, acting at once (four seeds, 0.45).** C1 **fail**: cameras with
p0:b3 against cameras with revision 6, -10.6 % [-50.3, +29.1] (per seed +22,
-5, -25, -34 %). C2 pass: no run with a teleport against two of four. C4 pass.
Not adopted. All eight camera runs were far below CC-A-CAMP on perfect data
(638,280-1,081,834 s against 1,964,859-2,669,145 s).

**D -- the district between "medium" and "heavy" (revision 7, ten seeds).**
D1 pass. D2: no. Busiest junction at 0.65: +4.0 % [-5.5, +13.5]; at 0.80:
-6.7 % [-16.8, +3.3]. A variant was used about once per run and a blocked
head was seen for 36 and 88 junction-seconds per run (the 3x3 grid: 600 to
1,600). On this network, with random-trip demand, the situation the
controller is built for hardly occurs.

**E -- two more single-lane networks (revision 7, ten seeds).**
- E1 pass as far as it was run (no violation).
- E2 **fail, and in the wrong direction.** On `narrow_grid54_lh` (20
  junctions, 150 m blocks, all at 0.38-0.45, variants used 194 and 284 times
  per run): +6.1 % [+1.7, +10.4] at 0.40, significantly *worse* than
  CC-A-CAMP, and +6.2 % [-1.7, +14.2] at 0.45. CC-A-CAMP does not lock this
  grid at 0.45 (4 teleports in ten runs; the 3x3 grid: 360 to 946).
- E3: no. On `narrow_rand_lh` the busiest junction that has a variant is at
  0.32, a variant was used less than once per run on average, and nothing
  changed (+1.1 %
  [-2.3, +4.4], -0.5 % [-3.9, +2.8]).

**What this means.** The gain measured three times on the 3x3 / 200 m grid is
real for that grid and does not carry over to the one other regular
single-lane grid tried, where the controller costs about 6 %. On the two
networks with uneven junction loads it does nothing. A diagnosis of the
difference between the two grids is in `dev/dev30_*` (training seeds).
