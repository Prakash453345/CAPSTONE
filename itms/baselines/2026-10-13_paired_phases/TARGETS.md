# Facing approaches share a green: targets set before the held-out runs

Written 2026-10-13T05:05Z (10:35 IST), before any run on seeds 269-273, which no
experiment in this project has used.

## What is being tested (`truth:pair`)

The 2026-10-13 check-up found every signal spending 22-38 % of its time in
yellow and all-red, and on two networks every phase serving a single approach
("split" phasing: four changes per cycle). `itms_domain.phase_layout.paired_layout`
rebuilds such a junction from its own geometry and conflict map: approaches
that face each other share a phase; straight-ahead traffic and turns that cross
nothing run protected; the turn that crosses the oncoming stream (right turn in
left-hand traffic, left turn in right-hand traffic, any U-turn) runs permissive
(SUMO 'g': green, give way). Webster's greens and the ceilings are then worked
out for the new phases. Junctions that are not split-phased, have pedestrian
signals, or where two straight streams of a pair would cross, are left as they
are. Only arterial_lh (6 of 6 lights) and grid4_rh_turns (16 of 16) are
changed; every other network's configuration is identical by construction.

## How it was chosen (training seeds 101-103, `dev/`)

| network | level | pair | pair + protected-turn phases |
|---|---|---|---|
| arterial_lh | light / medium / heavy | -22.5 % / -26.5 % / -28.2 % | +2.8 % / +6.8 % / +11.7 % |
| grid4_rh_turns | light / medium | -32.9 % / -42.2 % | -8.6 % / -24.6 % |

Every seed better with `pair`; no interlock violation, no teleport, no SUMO
collision warning. Protected-turn phases (`pairt`) were worse than `pair` and
are dropped.

## Held-out run

Arms `truth` and `truth:pair`, seeds 269-273: arterial_lh (light, medium,
heavy), grid4_rh_turns (light, medium). 50 runs. `run_eval.sh`, results in
`results/`.

Pass:
- **P1.** No interlock violation in any `truth:pair` run.
- **P2.** Each of the five network-levels: less person-delay with `truth:pair`,
  paired 95 % interval over the five seeds excluding zero.
- **P3.** No SUMO collision warning in any `truth:pair` run, and no
  network-level on which `truth:pair` teleports significantly more vehicles
  (paired 95 % interval of the per-seed difference entirely above zero).

If all three pass, `pair` becomes the default for split-phased junctions.

## Outcome (2026-10-13T08:45Z)

Held-out run complete (50 runs, seeds 269-273; `python summarise.py`). The run
was paused once by the user and resumed; nothing changed in between.

- P1 **pass**: no interlock violation.
- P2 **pass** on all five: arterial_lh light -23.2 % [-32.7, -13.7], medium
  -26.6 % [-31.9, -21.3], heavy -30.0 % [-37.9, -22.0]; grid4_rh_turns light
  -30.6 % [-33.3, -27.9], medium -41.6 % [-43.9, -39.4]. Better on every seed.
- P3 **pass**: no SUMO collision warning in any run, no teleport.

`pair` is **adopted** as the default (`truth`; `truth:nopair` is the controller
before it). Also in the live service (`sim_service/main.py`).
