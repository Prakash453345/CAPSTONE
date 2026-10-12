#!/usr/bin/env bash
# Development (TRAIN 101-103): the heavy district again after the wait guard was widened
# for rings of four or more phases (CC-A-CAMP: dev24_district_heavy). Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
while [ ! -f $O/dev25_done.txt ]; do sleep 15; done
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python $G --levels heavy --arms hol,hol:p0:b3 \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev26_district_heavy.json > $O/dev26_district_heavy.log 2>&1
echo done > $O/dev26_done.txt
