#!/usr/bin/env bash
# Development (TRAIN seeds), revision 6: does a larger family budget (3x the base phase's
# maximum green per visit instead of 2x) give back what the room check cost at 0.35?
# Starts after dev22. Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
while [ ! -f $O/dev22_done.txt ]; do sleep 20; done
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 --arms hol:b3 \
  --seed-list 101,102,103,104,105,106,107,108,109,110 --workers 2 --resume --out $O/dev23_sweep.json > $O/dev23_sweep.log 2>&1
echo done > $O/dev23_done.txt
