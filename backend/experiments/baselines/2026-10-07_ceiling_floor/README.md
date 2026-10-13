# A floor under the green ceiling, and Amaravati (2026-10-06/07)

**Status: simulation result. Adopted in the benchmark configuration. Not
committed.** Targets were written before the held-out runs (`TARGETS.md`).

## In one paragraph

CC-A-CAMP limits every green to 1.25 x Webster's green. In light and medium
traffic Webster's greens are short, so the limit was short as well (under
9 s on the planned Amaravati grid) and the controller kept cutting greens
off after a few vehicles, paying a change interval each time. With a floor
of 20 s under that limit, person-delay fell by 4.6 % on average over 20
light and medium network-levels on seeds never used before, was
significantly worse nowhere, and was unchanged in heavy traffic. On the
Amaravati plan grid it fell by 16 % in light traffic and 15 % in medium.

## How it was found

Amaravati was added as a test city in two forms:

- `amaravati_plan`: the planned arterial grid as a model (`grid:5x4,1000,3`,
  1 km blocks, three lanes and a turn lane, 20 lights).
- `amaravati`: the real map (OpenStreetMap, 2026-10-06), with the roads that
  are under construction promoted to the class and lane count the plan gives
  them (`scenarios/osm_planned_roads.py`; the ten priority E and N roads are
  four-lane, World Bank 2018). 122 lights.

On the plan grid CC-A-CAMP beat Webster at every level (`dev/am1.json`), but
its mean wait in light traffic (48 s) was longer than in heavy traffic
(31 s). The decision counters showed why: 69 % of all phase changes at light
demand were forced by the green ceiling. Floors of 20 s and 30 s and a
ceiling of 3 x Webster were then tried on training seeds 101-103 on six
networks (`dev/`, table in `TARGETS.md`); 30 s lost 21 % on the heavy
corridor, 20 s was never worse on average.

## Held-out result (seeds 221-225, `python summarise.py`)

| network | level | CC-A-CAMP (s) | with floor (s) | change, 95 % interval | better on | mean wait old / new (s) | stops old / new | entry wait, % of delay | teleports old / new |
|---|---|---|---|---|---|---|---|---|---|
| amaravati_plan | heavy | 417,787 | 417,787 | +0.0 % [+0.0, +0.0] | 0/5 | 32.4 / 32.4 | 2.39 / 2.39 | 5.5 | 1 / 1 |
| amaravati_plan | light | 117,075 | 104,578 | -10.8 % [-23.0, +1.4] | 4/5 | 47.8 / 42.1 | 2.49 / 1.91 | 1.9 | 0 / 0 |
| amaravati_plan | medium | 247,013 | 210,289 | -14.8 % [-18.5, -11.0] | 5/5 | 42.9 / 36.2 | 2.58 / 2.18 | 3.1 | 0 / 0 |
| arterial_lh | heavy | 280,284 | 280,982 | +0.4 % [-7.2, +8.0] | 2/5 | 61.2 / 61.8 | 2.28 / 2.24 | 0.7 | 0 / 0 |
| arterial_lh | light | 36,480 | 33,996 | -6.5 % [-16.4, +3.3] | 4/5 | 30.2 / 26.8 | 2.06 / 1.87 | 1.5 | 0 / 0 |
| arterial_lh | medium | 100,005 | 97,225 | -2.8 % [-8.3, +2.8] | 4/5 | 41.5 / 42.3 | 2.27 / 2.19 | 0.9 | 0 / 0 |
| berlin_adlershof | light | 15,758 | 15,044 | -4.5 % [-8.9, +0.0] | 5/5 | 10.8 / 9.5 | 1.19 / 1.13 | 1.7 | 0 / 0 |
| berlin_adlershof | medium | 40,105 | 39,350 | -1.9 % [-3.7, -0.0] | 5/5 | 14.2 / 13.6 | 1.38 / 1.34 | 1.7 | 0 / 0 |
| corridor | heavy | 505,833 | 491,248 | -0.4 % [-25.8, +25.0] | 2/5 | 91.7 / 87.6 | 2.81 / 2.84 | 23.1 | 0 / 1 |
| corridor | medium | 66,988 | 69,821 | +4.4 % [-3.0, +11.8] | 2/5 | 19.9 / 20.8 | 1.67 / 1.69 | 0.7 | 1 / 5 |
| grid3_lh | light | 55,244 | 56,267 | +2.1 % [-4.9, +9.1] | 2/5 | 13.4 / 13.3 | 1.62 / 1.66 | 1.9 | 0 / 0 |
| grid3_lh | medium | 142,533 | 148,825 | +4.7 % [-3.5, +12.8] | 2/5 | 19.0 / 19.7 | 2.28 / 2.36 | 1.8 | 0 / 0 |
| grid4_rh_turns | light | 41,790 | 36,435 | -12.8 % [-14.8, -10.8] | 5/5 | 41.3 / 34.9 | 2.77 / 2.45 | 2.5 | 0 / 0 |
| grid4_rh_turns | medium | 115,160 | 114,513 | -0.6 % [-3.2, +2.1] | 3/5 | 58.5 / 58.5 | 3.02 / 2.90 | 4.0 | 0 / 0 |
| ingolstadt | light | 6,505 | 6,471 | -0.5 % [-3.0, +2.0] | 2/5 | 9.2 / 9.3 | 0.80 / 0.79 | 4.7 | 0 / 0 |
| ingolstadt | medium | 28,352 | 27,572 | -0.9 % [-21.5, +19.6] | 2/5 | 21.2 / 20.6 | 1.66 / 1.61 | 38.6 | 0 / 0 |
| narrow_lh | light | 84,628 | 85,971 | +1.8 % [-10.0, +13.5] | 3/5 | 20.0 / 19.8 | 2.23 / 2.21 | 1.8 | 0 / 0 |
| random_lh | light | 59,636 | 52,440 | -11.7 % [-23.3, +0.0] | 5/5 | 23.5 / 21.8 | 2.50 / 2.34 | 1.2 | 0 / 0 |
| random_lh | medium | 129,039 | 125,228 | -2.8 % [-11.8, +6.2] | 4/5 | 28.3 / 27.5 | 2.75 / 2.75 | 1.3 | 0 / 0 |
| spider_lh | light | 72,775 | 67,123 | -7.5 % [-18.6, +3.7] | 4/5 | 14.4 / 12.7 | 1.64 / 1.51 | 2.3 | 14 / 4 |
| spider_lh | medium | 157,380 | 145,805 | -7.3 % [-10.0, -4.6] | 5/5 | 18.4 / 16.8 | 1.95 / 1.86 | 2.5 | 46 / 52 |
| vijayawada_district | light | 83,373 | 77,892 | -6.5 % [-9.6, -3.4] | 5/5 | 17.4 / 16.8 | 2.03 / 1.98 | 0.9 | 0 / 0 |
| vijayawada_district | medium | 205,292 | 175,738 | -12.5 % [-31.2, +6.3] | 3/5 | 29.8 / 21.3 | 2.26 / 2.16 | 0.8 | 14 / 5 |

Targets: F1 pass (no violation). F2 pass: -4.6 % [-7.2, -1.9] over the 20
light and medium network-levels, better on 16. F3 failed at light on these
five seeds (-10.8 % [-23.0, +1.4]) and passed at medium; the follow-up
registered for it, on ten more new seeds (226-235, `results_f3b/`), passed:
**-16.4 % [-21.2, -11.6], better on all ten**. F4 pass: significantly worse
nowhere. F5 pass: heavy unchanged.

## The real Amaravati map: first measurement, not yet usable

Training seeds 101-103, CC-A-CAMP (before the floor) against Webster
(`dev/base.json`): heavy -52 %, -21 %, -31 %; medium -17 %, -31 % (two
seeds); light -35 %, -6 %, +3 %. In light traffic CC-A-CAMP had vehicles
removed from jams (8 and 12 in two runs) where Webster had none, and both
controllers had them at medium. They cluster around one junction
(`joinedS_3302353029_7905475494`). That is either a fault in how this map
converts to a network or a real weakness of the controller at an awkward
junction, and it has to be understood before any number from this network
means anything. Runs there take 4 to 21 minutes each.

## Limits

- Five seeds per network-level. The average over networks is solid; single
  rows mostly are not (most intervals include zero).
- Not better everywhere: corridor medium +4.4 %, grid3_lh +2.1 % and +4.7 %,
  narrow_lh light +1.8 %, arterial_lh heavy +0.4 % (none significant).
- The floor was picked from two values. 30 s gains more in light traffic and
  costs on the heavy corridor; a floor that depends on load might do better.
- Even with the floor, the mean wait on the Amaravati plan grid in light
  traffic is 40 s. Most of that is still there to be won, probably by
  not serving empty phases and by coordinating neighbouring lights.
- This is the configuration the benchmarks use (`scripts/m8_harness.py`).
  The network extractor's own default ceiling is a flat 90 s
  (`extract_tier0_config.py`); whether the live service applies the Webster
  ceiling at all has not been checked here.
- The plan grid is a model with one layout and random-trip demand, not a
  forecast of Amaravati's traffic.
- Person-delay does not include the wait to enter the network (reported in
  the table: under 3 % of person-delay on most rows, 23 % on the heavy
  corridor and 39 % on Ingolstadt medium) or vehicles unfinished at the end.

## Files

`TARGETS.md`, `run_eval.sh`, `run_f3b.sh`, `summarise.py`, `results/`,
`results_f3b/`, `dev/` (training-seed runs and their scripts).
