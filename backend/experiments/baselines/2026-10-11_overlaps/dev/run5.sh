#!/usr/bin/env bash
# Training seeds 104-113, district at medium demand: is ovl3's +7 % there systematic?
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/overlaps
while [ ! -f $O/done4.txt ]; do sleep 10; done
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
  --levels medium --arms truth,truth:ovl3 --seed-list 104,105,106,107,108,109,110,111,112,113 \
  --out $O/district_more.json > $O/district_more.log 2>&1
echo done > $O/done5.txt
