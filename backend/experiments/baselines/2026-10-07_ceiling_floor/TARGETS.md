# A floor under the green ceiling: targets set before the held-out runs

Written 2026-10-06T20:50Z (2026-10-07 02:20 IST), before any run on seeds
221-225, which no experiment in this project has used.

## What is being tested

CC-A-CAMP's ceiling on a green is 1.25 x Webster's green for that phase. At
light and medium demand Webster returns short greens (its minimum cycle), so
the ceiling is short too: under 9 s on the four-phase junctions of the
planned Amaravati grid, under 20 s for most phases of most networks. The
controller is then forced off a green every few vehicles and pays a change
interval each time. On the Amaravati plan grid at light demand 69 % of all
phase changes were forced by the ceiling and the mean wait (48 s) was longer
than at heavy demand (31 s).

The change: no phase's ceiling is below 20 s (`truth:f20`). Where Webster's
greens are already longer, nothing changes.

## How it was chosen (training seeds 101-103 only, `dev/`)

Floors of 20 s and 30 s and a ceiling of 3 x Webster on the Amaravati plan
grid; 20 s and 30 s on five more networks. Mean change in person-delay
against CC-A-CAMP, three seeds each:

| network | level | floor 20 s | floor 30 s |
|---|---|---|---|
| Amaravati plan grid | light / medium / heavy | -16 % / -16 % / 0 % | -20 % / -21 % / +1 % |
| arterial_lh | light / medium | -7 % / -3 % | -15 % / -6 % |
| corridor (Vijayawada) | medium / heavy | -7 % / -10 % | -3 % / +21 % |
| grid4_rh_turns | light / medium | -9 % / -1 % | -14 % / -1 % |
| berlin_adlershof | light / medium | -4 % / -3 % | -11 % / -1 % |
| grid3_lh | light / medium | -4 % / -2 % | -4 % / -1 % |

30 s gains more in light traffic and lost 21 % on the heavy corridor (two of
three seeds); 20 s was never worse on average. So 20 s. Ingolstadt, the
spider, the irregular net, the district and the single-lane grid were not
looked at.

## Held-out run

Arms `truth` (CC-A-CAMP as it is) and `truth:f20`, seeds 221-225, on every
network and level where some phase's ceiling is under 20 s:
Amaravati plan grid, arterial_lh (light, medium, heavy); corridor (medium,
heavy); grid3_lh, grid4_rh_turns, berlin_adlershof, ingolstadt, spider_lh,
random_lh, vijayawada_district (light, medium); narrow_lh (light).
22 network-levels, 220 runs. `run_eval.sh`, results in `results/`.

Person-delay as before (SUMO `timeLoss` of finished trips); the wait to
enter the network (`entry_delay_s`) is reported beside it.

Pass:
- **F1.** No interlock violation in any `truth:f20` run.
- **F2.** Across the 19 light and medium network-levels: the mean of the
  per-network-level changes in person-delay is below zero, 95 % t interval
  (over the 19) excluding zero.
- **F3.** Amaravati plan grid, light and medium each: `truth:f20` has less
  person-delay, paired 95 % interval over the five seeds excluding zero.
- **F4.** No network-level, heavy included, on which `truth:f20` is
  significantly worse (paired 95 % interval entirely above zero).
- **F5.** The three heavy network-levels together: mean change not above
  +5 %.

If F1-F5 pass, the floor becomes part of CC-A-CAMP's default configuration.
The real-map Amaravati network (`scenarios/generated/amaravati`, 122 lights,
built from OpenStreetMap with the roads under construction promoted) is not
part of this run: its first measurement showed vehicles removed from jams at
light demand under CC-A-CAMP, which has to be understood first.

## Outcome (2026-10-07T01:40Z)

`python summarise.py`. (The count above was off by one: there are 23
network-levels, 20 of them light or medium.)

- F1 pass: no violation.
- F2 pass: -4.6 % [-7.2, -1.9] over the 20 light and medium network-levels,
  better on 16.
- F3 **fail at light**: Amaravati plan grid light -10.8 % [-23.0, +1.4]
  (better on 4 of 5 seeds); medium -14.8 % [-18.5, -11.0] passes.
- F4 pass: significantly worse nowhere. Worse on average, not significantly:
  corridor medium +4.4 %, grid3_lh +2.1 % and +4.7 %, narrow_lh light +1.8 %,
  arterial_lh heavy +0.4 %.
- F5 pass: heavy 0.0 %, +0.4 %, -0.4 %.

By the rule above the floor is not adopted on this run alone, because F3
missed at light.

## Follow-up F3b, written 2026-10-07T01:40Z before it was run

A new test on new seeds, not an extension of the sample above: Amaravati
plan grid, light demand, `truth` and `truth:f20`, seeds 226-235 (never
used). **F3b: `truth:f20` has less person-delay, paired 95 % interval over
the ten seeds excluding zero.** If F3b passes, the floor is adopted (F1, F2,
F4, F5 having passed); if not, it is not.

### Outcome of F3b (2026-10-07T02:35Z)

Pass: -16.4 % [-21.2, -11.6] over the ten new seeds, better on all ten (mean
wait 48.7 s -> 40.1 s, stops per vehicle 2.47 -> 1.85). The floor is adopted:
`CEILING_FLOOR_S = 20.0` in `scripts/m8_harness.py`; `truth:f0` and `hol:f0`
are the controllers without it.
