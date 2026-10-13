# Free turns shown in every phase they fit: targets set before the held-out runs

Written 2026-10-11T16:29Z (21:59 IST), before any run on seeds 256-260, which no experiment
in this project has used.

## What is being tested (`truth:ovl3`)

A signal program from netconvert gives each movement one phase. A movement
that crosses nothing in another phase (a left turn in left-hand traffic, a
right turn beside the opposite left, many U-turns) still waits through that
phase on red. The change shows every such movement green in every phase it
conflicts with nothing in (`itms_domain.overlaps.with_overlaps`, read off
SUMO's own conflict matrix both ways; pedestrian signals never added). The
movements are *shown* with the phase but not *owned* by it
(`Phase.overlap_movements`): the signal shows them and the interlocks check
them (I1 against the phase, clearance on every change, wait clocks reset when
they run), while the controller's pressure, demand, gap-out and the Webster
timing read only the phase's own movements, exactly as before.

## How it was chosen (training seeds 101-113 only, `dev/`)

Mean change in person-delay against CC-A-CAMP as it is (`truth`: 20 s floor,
every waiting vehicle seen), three seeds each unless said:

| network | light | medium | heavy |
|---|---|---|---|
| arterial_lh | -11.6 % | -30.1 % | -30.9 % |
| grid4_rh_turns | -19.5 % | -18.5 % | |
| Amaravati plan grid | -4.6 % | -3.3 % | -1.1 % |
| spider_lh | -10.6 % | -9.8 % | |
| random_lh | +4.2 % | -9.2 % | |
| berlin_adlershof | +1.2 % | -0.4 % | |
| corridor | | -3.7 % | -17.9 % |
| vijayawada_district | -3.1 % | +7.4 %; 10 more seeds +3.2 % [-17.9, +24.3], better on 6 | |
| Amaravati real map (`amaravati_v2`) | -9.8 %, teleports 3 -> 0 | | |

No interlock violation in any run. Earlier forms, dropped:
- `ovl`: overlaps owned by the phases they were added to, Webster's split
  worked out after. Webster then evened out the greens (arterial_lh main road
  80 s -> 51 s) and heavy demand lost 70 %.
- `ovl2`: owned, timing kept. Every phase now carried the free turns' queues,
  so none could gap out: heavy +45 % on arterial_lh.
- `ovl4`: `ovl3` without U-turns. Worse on the real Amaravati map (+6.5 %,
  where 51 of 89 overlaps are U-turns) and no better on the district.

Networks where it adds nothing (grid3_lh, ingolstadt) are not run.

## Held-out run

Arms `truth` and `truth:ovl3`, seeds 256-260: Amaravati plan grid and
arterial_lh (light, medium, heavy); corridor (medium, heavy); grid4_rh_turns,
spider_lh, random_lh, berlin_adlershof, vijayawada_district (light, medium);
the real Amaravati map `amaravati_v2` (light). 19 network-levels, 190 runs.
`run_eval.sh`, results in `results/`.

Pass:
- **O1.** No interlock violation in any `truth:ovl3` run.
- **O2.** Light and medium, the 15 network-levels other than the real map:
  mean of the per-network-level changes below zero, 95 % t interval over the
  15 excluding zero.
- **O3.** Heavy (plan grid, arterial_lh, corridor): mean change below zero.
- **O4.** No network-level, the real map included, on which `truth:ovl3` is
  significantly worse (paired 95 % interval over the five seeds entirely above
  zero).
- **O5.** No network-level on which `truth:ovl3` teleports significantly more
  vehicles (paired 95 % interval of the per-seed difference entirely above
  zero).

If all five pass, `ovl3` becomes the default. Otherwise it is not adopted.

## Outcome (2026-10-12T06:07Z)

Held-out run complete (190 runs, seeds 256-260; `python summarise.py`).

- O1 **pass**: no interlock violation in any `truth:ovl3` run.
- O2 **pass**: light and medium, 15 network-levels, -6.4 % [-12.2, -0.6],
  better on 9 of 15.
- O3 **pass**: heavy -11.8 % on average (plan grid +0.6 %, arterial_lh
  -24.3 %, corridor -11.7 %).
- O4 **pass**: significantly worse on no network-level. Worst: district
  medium +7.3 % [-12.2, +26.8], Berlin medium +3.7 % [-4.8, +12.2].
- O5 **pass**: significantly more teleports on no network-level.

Real Amaravati map (light): -2.3 % [-12.2, +7.6], teleports 1 -> 0.

All five pass: `ovl3` is **adopted** as the default (`truth`; `truth:noovl`
is the controller before it). The run was paused once by the user and resumed
(the last two real-map runs); no target or code changed in between.

Corrections found by an independent check afterwards (the text above is left
as written): owned overlaps raised person-delay by 70 % (not "lost 70 %");
under `ovl2` gap-outs fell to 25-41 per run, not to none; `ovl4`'s +6.5 % on
the real map is not significant, and it beat `ovl3` on the corridor at heavy
demand (-24.7 % against -17.9 %); the district's three training seeds at
medium were significantly worse (+7.4 % [+4.0, +10.7]).
