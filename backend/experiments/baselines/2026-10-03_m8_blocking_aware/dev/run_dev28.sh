#!/usr/bin/env bash
# Development (TRAIN 104-110): the heavy district on seven more seeds, CC-A-CAMP and the new
# default -- three seeds gave -59 %, -16 % and +76 %, which says nothing. Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/hol
while [ ! -f $O/dev27_done.txt ]; do sleep 15; done
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python scripts/m8_closed_loop_gate.py --levels heavy --arms truth,hol \
  --seed-list 104,105,106,107,108,109,110 --workers 2 --resume --out $O/dev28_district_heavy.json > $O/dev28_district_heavy.log 2>&1
echo done > $O/dev28_done.txt
