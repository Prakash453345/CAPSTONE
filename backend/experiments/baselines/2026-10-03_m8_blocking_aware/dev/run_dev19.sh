#!/usr/bin/env bash
# Development (TRAIN seeds): how to leave a variant, now that going back to the base phase
# costs an ordinary change. hol = back when the base phase would release more or the
# approach is empty; hol:idle = only when empty; hol:term = move on instead while another
# phase waits. CC-A-CAMP: dev13. (hol itself: dev18.)
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 --arms hol:idle,hol:term \
  --seed-list 101,102,103,104,105 --workers 2 --resume --out $O/dev19_sweep.json > $O/dev19_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms hol:idle,hol:term \
  --seed-list 101,102,103,104,105,106,107,108,109,110 --workers 2 --resume --out $O/dev19_light.json > $O/dev19_light.log 2>&1
echo done > $O/dev19_done.txt
