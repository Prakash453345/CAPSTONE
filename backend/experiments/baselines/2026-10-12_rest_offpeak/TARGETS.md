# Rest in green as an off-peak mode: targets set before the held-out runs

Written 2026-10-12T15:38Z (21:08 IST), before any run on seeds 264-268, which no experiment
in this project has used.

## What is being tested (`truth:rest`)

At its green ceiling CC-A-CAMP changes phase even when every other phase is
empty (no queue, nobody arriving within 8 s, no wait near its bound, no
pedestrian phase), paying a change interval for nothing. With
`AcampConfig.rest_in_green` it stays green instead. It is tested here as an
**off-peak mode**: something an operator switches on for light-traffic hours
(night, weekends), as many cities run their signals differently off-peak. It
is not tested for, and would not be switched on in, medium or heavy traffic.

On top of today's default: 20 s floor under the ceiling, every waiting vehicle
seen, free turns shown in every phase they fit.

## How it was chosen (training seeds 101-103, `dev/`)

Mean change in person-delay against `truth`, three seeds each:

| network | light | medium | heavy |
|---|---|---|---|
| arterial_lh | -15.0 % | +5.2 % | +3.5 % |
| berlin_adlershof | -16.8 % | -3.5 % | |
| random_lh | -16.5 % | -1.1 % | |
| vijayawada_district | -10.2 % | -9.6 % | |
| Amaravati plan grid | -6.6 % | -0.9 % | |
| grid4_rh_turns | -3.9 % | +0.2 % | |
| spider_lh | -1.0 % | -0.9 % | |
| ingolstadt | +1.5 % | -12.8 % | |
| grid3_lh | +1.7 % | -0.2 % | |
| corridor | | -5.6 % | -1.1 % |
| Amaravati real map | -5.0 % (one seed) | | |
| **mean** | **-7.2 % (10)** | **-2.9 % (10)** | +1.2 % (2) |

Light is where the gain is. arterial_lh lost at medium and heavy on all three
seeds, hence off-peak only. Tried and dropped (training seeds): a cap on how
long a green may rest (`restm`), resting only below a load threshold
(`restc`), only while no other road has a vehicle on it (`restq`), and only
while the running phase still has traffic (`restd`, light -3.2 % on average,
medium +1.2 %). Before the free-turn change, rest on fresh seeds (2026-10-07)
gave -6.5 % at light over 10 network-levels and failed only a teleport-count
target that compared two noisy totals.

## Held-out run

Arms `truth` and `truth:rest`, light demand, seeds 264-268, on the ten
networks with a light level: Amaravati plan grid, arterial_lh, grid4_rh_turns,
berlin_adlershof, spider_lh, random_lh, grid3_lh, ingolstadt,
vijayawada_district, narrow_lh (100 runs). Then the real Amaravati map
(`amaravati_v2`, light, seeds 264-266, 6 runs): reported, and included in
targets L3 and L4. `run_eval.sh`, results in `results/`.

Pass:
- **L1.** No interlock violation in any `truth:rest` run.
- **L2.** Over the ten light network-levels: mean change below zero, 95 % t
  interval over the ten excluding zero.
- **L3.** No network-level, the real map included, on which `truth:rest` is
  significantly worse (paired 95 % interval entirely above zero).
- **L4.** No network-level on which `truth:rest` teleports significantly more
  vehicles (paired 95 % interval of the per-seed difference entirely above
  zero).

If all four pass, rest in green becomes an **off-peak mode** (a switch, off by
default, documented for light-traffic hours). It stays off in the benchmark's
medium and heavy runs either way.

## Outcome (2026-10-12T17:50Z)

Held-out run complete (100 runs on ten networks, 6 on the real map;
`python summarise.py`).

- L1 **pass**: no interlock violation.
- L2 **pass**: light, ten network-levels, -6.8 % [-11.6, -1.9], better on 8.
  Random net -17.4 %, Berlin -15.1 %, Amaravati plan grid -13.0 %, district
  -9.9 %.
- L3 **pass**: significantly worse nowhere (real Amaravati map -9.4 %
  [-34.9, +16.1], three seeds).
- L4 **fail**: spider_lh teleported more vehicles with rest on all five
  seeds but one (4/1/2/1/0 against 4/3/3/3/2; per-seed difference +1.4
  [+0.3, +2.5]).

**Not adopted**: all four had to pass. `rest_in_green` stays off.

What the spider's teleports are (training seeds 101-104, run afterwards): all
are SUMO *collision* teleports ("collision with vehicle ... gap < 0") on one
lane, A1B4, with the controller as it is too (four in four runs). They are
rear-end collisions in SUMO's driver model on that lane, not vehicles stranded
by a red. Rest in green makes them more frequent there; why was not found.

Correction (2026-10-13): the collisions are on all five exits of the centre junction A1
(A1B1..A1B5), not A1B4 alone; A1 is `unregulated` in the generated network. See
`baselines/2026-10-13_rest_offpeak_v2`.
