#!/usr/bin/env bash
# Development (TRAIN seeds), the final controller: variants and pricing only for single-lane
# approaches, and only once a blockage has lasted a change interval. CC-A-CAMP on the same
# seeds is in dev5 (single-lane grid), dev3 (its medium) and dev7 (other networks).
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms hol \
  --seed-list 101,102,103,104,105,106,107,108,109,110 --workers 2 --resume --out results/hol/dev11_light.json > results/hol/dev11_light.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 --arms hol \
  --seed-list 101,102,103,104,105 --workers 2 --resume --out results/hol/dev11_sweep.json > results/hol/dev11_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels medium --arms hol \
  --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev11_medium.json > results/hol/dev11_medium.log 2>&1
.venv/bin/python $G --levels medium,heavy --arms hol --seed-list 101,102,103 --workers 2 --resume \
  --out results/hol/dev11_corridor.json > results/hol/dev11_corridor.log 2>&1
ITMS_SCENARIO=scenarios/generated/berlin_adlershof .venv/bin/python $G --levels light,heavy --arms hol \
  --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev11_berlin_adlershof.json > results/hol/dev11_berlin_adlershof.log 2>&1
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python $G --levels light,medium,heavy --arms hol \
  --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev11_vijayawada_district.json > results/hol/dev11_vijayawada_district.log 2>&1
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python $G --levels medium --arms truth \
  --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev11_vijayawada_district_truth_medium.json > results/hol/dev11_vijayawada_district_truth_medium.log 2>&1
echo done > results/hol/dev11_done.txt
# cameras in the loop, with the overview cameras (nothing else running, for speed)
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d45 --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out results/hol/dev12_cam_sweep.json > results/hol/dev12_cam_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out results/hol/dev12_cam_light.json > results/hol/dev12_cam_light.log 2>&1
echo done > results/hol/dev12_done.txt
