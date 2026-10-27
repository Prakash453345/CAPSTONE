# Rest in green as an off-peak mode, second test: targets set before the held-out runs

Written 2026-10-13T10:55Z (16:25 IST), before any run on seeds 274-278, which no experiment in
this project has used.

## Why a second test

The first test (baselines/2026-10-12_rest_offpeak) passed L1-L3 (light, ten networks,
-6.8 % [-11.6, -1.9]) and failed L4 on spider_lh teleports only. Since then:

1. **The spider's teleports are a network defect.** netgenerate left the spider's centre
   junction A1 `unregulated` (five two-lane roads, every connection state `M`: nobody
   yields). Every collision found in the spider logs (113 in the check-up and rest-guard
   runs) is on one of A1's five exits (A1B1..A1B5), never at a signal. With A1 signalised
   (`scenarios/generated/spider_lh_tl`, netconvert with A1 as a traffic light, layout
   `opposites`; the other 15 programs and their links unchanged), training seeds
   101-103 gave **zero collisions and zero teleports** with rest on or off (light
   +0.2 %, medium -7.1 % with an interval of [-48, +34]: no evidence either way on delay). Making A1 a priority junction instead (`spider_lh_pri`)
   removed the collisions but gridlocked its minor roads (yield teleports), so it is
   not used.
2. **The default changed**: paired phases on split-phased junctions (2026-10-13).
   On training seeds rest still gains there: arterial_lh light -16.9 % [-15, -14, -21],
   grid4_rh_turns light -9.3 % [-7, -11, -10] (`dev/`).

## Held-out run

Arms `truth` (today's default: 20 s floor, split-road sensing, shown overlaps, paired
split junctions) and `truth:rest`, **light demand only**, seeds 274-278, on:
arterial_lh, berlin_adlershof, grid4_rh_turns, **spider_lh_tl**, random_lh, grid3_lh,
ingolstadt, narrow_lh, amaravati_plan, vijayawada_district (the ten of the first test,
with the corrected spider). Also, reported: the original spider_lh (seeds 274-278) and
the real Amaravati map (amaravati_v2, seeds 274-276). `run_eval.sh`, results in `results/`.

Pass (same as the first test, with the spider rule stated in advance):
- **L1.** No interlock violation in any `truth:rest` run.
- **L2.** Over the ten light network-levels above: mean change below zero, 95 % t
  interval over the ten excluding zero.
- **L3.** No network-level, the original spider and the real map included, on which
  `truth:rest` is significantly worse (paired 95 % interval entirely above zero).
- **L4.** No network-level on which `truth:rest` teleports significantly more vehicles
  (paired 95 % interval of the per-seed difference entirely above zero). The original
  spider_lh is reported but **excluded from L4**, for the reason in (1).

If all four pass, rest in green becomes an **off-peak mode**: a switch, off by default,
for light-traffic hours (an operator's time-of-day plan). It stays off in medium and heavy
traffic (arterial_lh lost 5 % at medium on training seeds in the first test).

## Outcome (2026-10-13T12:21Z)

Held-out run complete (110 runs on eleven networks, 6 on the real map; `python summarise.py`,
`results/SUMMARY.md`).

- L1 **pass**: no interlock violation.
- L2 **pass**: light, ten network-levels, -9.0 % [-12.4, -5.7]; lower on all ten,
  significantly on six (ingolstadt and narrow_lh about -1.5 %).
- L3 **pass**: significantly worse nowhere; the real Amaravati map -15.3 % [-18.8, -11.8]
  (3/3 seeds), the original spider -4.3 % [-11.4, +2.8].
- L4 **pass**: significantly more teleports nowhere (original spider, excluded as set
  above: 7 before, 10 after; real map 1 before, 0 after).

**Adopted as an off-peak mode**: `AcampConfig.rest_in_green` stays off by default; the
live service switches it on with `SIGNAL_OFFPEAK_REST=1`. Gate arm: `truth:rest`.
