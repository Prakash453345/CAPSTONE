#!/usr/bin/env bash
# Development (TRAIN seeds), revision 3: a variant leaves the other approach's yielding turn
# permissive, so the approach it serves keeps its green through the change in without a
# yellow trap. CC-A-CAMP on the same seeds: dev13.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 --arms hol,hol:nobudget \
  --seed-list 101,102,103,104,105 --workers 2 --resume --out $O/dev16_sweep.json > $O/dev16_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms hol,hol:nobudget \
  --seed-list 101,102,103,104,105,106,107,108,109,110 --workers 2 --resume --out $O/dev16_light.json > $O/dev16_light.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels medium --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev16_medium.json > $O/dev16_medium.log 2>&1
echo done > $O/dev16_done.txt
