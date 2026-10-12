#!/usr/bin/env bash
# Training seeds 101-103: truth:ovl4 (ovl3 without U-turns) where U-turns were among the
# overlaps, and random_lh light (the one light loss). Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/overlaps
while [ ! -f $O/v2_done.txt ]; do sleep 10; done
run() { ITMS_SCENARIO=scenarios/generated/$1 .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
  --levels $2 --arms $3 --seed-list 101,102,103 --out $O/$1.json > $O/${1}_4_$2.log 2>&1; }
run vijayawada_district light,medium truth:ovl4
unset ITMS_SCENARIO
.venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume --levels medium,heavy \
  --arms truth:ovl4 --seed-list 101,102,103 --out $O/corridor.json > $O/corridor_4.log 2>&1
run amaravati_v2 light truth:ovl4
echo done > $O/done4.txt
