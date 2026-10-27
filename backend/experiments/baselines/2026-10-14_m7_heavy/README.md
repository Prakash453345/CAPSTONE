# M7 green corridor under congestion (2026-10-14)

**Status: simulation result. Claim not supported. Nothing adopted. Not committed.**

Question: the 14 Oct re-run found the corridor engine no better than field-standard reactive
preemption at medium demand. Does it beat it under congestion (heavy demand)?

- Training seeds 101-105 suggested yes at heavy (-38.8 s EV travel time) and no at medium
  (+10.8 s). Two variants were tried there and dropped (`TARGETS.md`).
- Held-out seeds 284-293, targets written first, unchanged code, current CC-A-CAMP inputs:
  heavy **+3.6 s [-30.8, +38.0]** EV travel time, +1.5 stops (n.s.), person-delay -2.0 % (n.s.),
  zero violations; medium +5.6 s [-1.6, +12.8]. H1 failed.

Conclusion: on this corridor the corridor engine and reactive preemption are equivalent for the
emergency vehicle at both demand levels, with the corridor making slightly more stops. The value
of M7 is preemption itself (both cut EV travel time by about 150 s against no preemption on the
current controller, 14 Oct re-run) plus dispatch to the right hospital; the corridor engine's
route-level timing adds nothing measurable here.

Files: `TARGETS.md` (targets, outcome), `summarise.py`, `results/` (held-out JSON lines,
`SUMMARY.txt`), `dev/` (training-seed runs, including `corridor_union`, `corridor_noAD`).
Runner: `run_train.py`-style loop over `scripts/m7_corridor_benchmark.run_one` with
`m8_harness.ccacamp_inputs(level)`.
