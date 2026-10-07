#!/usr/bin/env bash
# Development (TRAIN seeds), after the simulator-side blocked-lane rule was corrected
# (a turner whose tail has cleared the stop line) and the 2 s grace was added:
# blockage must outlast 0 or 1 change intervals; pricing only. CC-A-CAMP is dev5's.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
A=hol:p0,hol,hol:price
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms $A \
  --seed-list 101,102,103,104,105,106,107,108,109,110 --workers 2 --resume --out results/hol/dev6_light.json > results/hol/dev6_light.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 --arms $A \
  --seed-list 101,102,103,104,105 --workers 2 --resume --out results/hol/dev6_sweep.json > results/hol/dev6_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels medium --arms hol:p0,hol \
  --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev6_medium.json > results/hol/dev6_medium.log 2>&1
echo done > results/hol/dev6_done.txt
