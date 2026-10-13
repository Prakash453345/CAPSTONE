#!/usr/bin/env bash
# Development (TRAIN seeds): which variant-entry rule. Arms: gain margin 0.1 / 0.5 / 1.0,
# blockage must outlast 1 / 2 change intervals, pricing only, CC-A-CAMP.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
A=truth,hol,hol:price,hol:p1,hol:p2,hol:m0.5,hol:m1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms $A \
  --seed-list 101,102,103,104,105,106,107,108,109,110 --workers 2 --resume --out results/hol/dev5_light.json > results/hol/dev5_light.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 --arms $A \
  --seed-list 101,102,103,104,105 --workers 2 --resume --out results/hol/dev5_sweep.json > results/hol/dev5_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels medium --arms hol,hol:p1 \
  --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev5_medium.json > results/hol/dev5_medium.log 2>&1
echo done > results/hol/dev5_done.txt
