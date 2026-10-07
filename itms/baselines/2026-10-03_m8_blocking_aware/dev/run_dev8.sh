#!/usr/bin/env bash
# Development (TRAIN seeds 101-102): the blocking-aware controller fed by cameras, with one
# overview camera per junction telling it which lanes are blocked, on the single-lane grid.
cd "$(dirname "$0")/../.."
while [ ! -f results/hol/dev7_done.txt ]; do sleep 20; done
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d45,d40 --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out results/hol/dev8_sweep.json > results/hol/dev8_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out results/hol/dev8_light.json > results/hol/dev8_light.log 2>&1
echo done > results/hol/dev8_done.txt
