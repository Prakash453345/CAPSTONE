#!/usr/bin/env bash
# Development (TRAIN seeds 101-103): the blocking-aware controller against CC-A-CAMP on the
# other networks, light and heavy demand -- looking for harm before any held-out run.
cd "$(dirname "$0")/../.."
while [ ! -f results/hol/dev6_done.txt ]; do sleep 20; done
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
for S in grid4_rh_turns arterial_lh grid3_lh spider_lh random_lh ingolstadt berlin_adlershof vijayawada_district; do
  ITMS_SCENARIO=scenarios/generated/$S .venv/bin/python $G --levels light,heavy --arms truth,hol \
    --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev7_$S.json > results/hol/dev7_$S.log 2>&1
done
.venv/bin/python $G --levels medium,heavy --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev7_corridor.json > results/hol/dev7_corridor.log 2>&1
echo done > results/hol/dev7_done.txt
