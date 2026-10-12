#!/usr/bin/env bash
# Development (TRAIN seeds 101-105): which part of revision 2 costs the gain at moderate
# demand -- the visit budget, or the ordinary change into a variant -- and whether a longer
# green ceiling alone (no blocking logic) does the same thing.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 \
  --arms hol:nobudget,hol:b3,hol:trap,hol:trap:b2,truth:c2,truth:c3 \
  --seed-list 101,102,103,104,105 --workers 2 --resume --out results/hol/dev15_sweep.json > results/hol/dev15_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light \
  --arms hol:nobudget,hol:trap,truth:c2,truth:c3 \
  --seed-list 101,102,103,104,105,106,107,108,109,110 --workers 2 --resume --out results/hol/dev15_light.json > results/hol/dev15_light.log 2>&1
echo done > results/hol/dev15_done.txt
