#!/usr/bin/env bash
# Development (TRAIN seeds), revision 2 of the blocking-aware controller (after the code
# review): ordinary change into a variant, family time budget, idle exit, tighter camera test.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms truth,hol \
  --seed-list 101,102,103,104,105,106,107,108,109,110 --workers 2 --resume --out $O/dev13_light.json > $O/dev13_light.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 --arms truth,hol \
  --seed-list 101,102,103,104,105 --workers 2 --resume --out $O/dev13_sweep.json > $O/dev13_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels medium --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev13_medium.json > $O/dev13_medium.log 2>&1
.venv/bin/python $G --levels medium,heavy --arms truth,hol --seed-list 101,102,103 --workers 2 --resume \
  --out $O/dev13_corridor.json > $O/dev13_corridor.log 2>&1
ITMS_SCENARIO=scenarios/generated/berlin_adlershof .venv/bin/python $G --levels light,heavy --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev13_berlin_adlershof.json > $O/dev13_berlin_adlershof.log 2>&1
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python $G --levels light,medium,heavy --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev13_vijayawada_district.json > $O/dev13_vijayawada_district.log 2>&1
echo done > $O/dev13_done.txt
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d45 --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out $O/dev14_cam_sweep.json > $O/dev14_cam_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out $O/dev14_cam_light.json > $O/dev14_cam_light.log 2>&1
echo done > $O/dev14_done.txt
