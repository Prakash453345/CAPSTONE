#!/usr/bin/env bash
# Development (TRAIN): the new default (p0:b3, wait guard widened for rings of three or
# more phases) where the guard matters and with cameras in the loop. Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python $G --levels heavy --arms hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev27_district_heavy.json > $O/dev27_district_heavy.log 2>&1
.venv/bin/python $G --levels medium,heavy --arms hol --seed-list 101,102,103 --workers 2 --resume \
  --out $O/dev27_corridor.json > $O/dev27_corridor.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d40 --arms hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev27_same.json > $O/dev27_same.log 2>&1
echo done > $O/dev27a_done.txt
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d45 --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out $O/dev27_cam_sweep.json > $O/dev27_cam_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out $O/dev27_cam_light.json > $O/dev27_cam_light.log 2>&1
echo done > $O/dev27_done.txt
