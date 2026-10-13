#!/usr/bin/env bash
# Follow-up S4b (TARGETS.md, amendment 1): the district at medium demand on 10 new seeds.
# Run from itms/; resumable.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
B=baselines/2026-10-07_split_road_sensing
while [ ! -f $B/results/eval_done.txt ]; do sleep 15; done
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume --levels medium \
  --arms truth,truth:via2 --seed-list 246,247,248,249,250,251,252,253,254,255 \
  --out $B/results_s4b/vijayawada_district.json > $B/results_s4b/vijayawada_district.log 2>&1
echo done > $B/results_s4b/done.txt
