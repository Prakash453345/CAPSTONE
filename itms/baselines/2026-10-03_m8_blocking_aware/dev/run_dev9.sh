#!/usr/bin/env bash
# Development (TRAIN seeds 101-103): the whole-approach rule on the networks where the
# first version (one blocked lane is enough) did harm at heavy demand. CC-A-CAMP is dev7's.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
ITMS_SCENARIO=scenarios/generated/grid3_lh .venv/bin/python $G --levels heavy --arms hol,hol:lane,hol:lane:m1,hol:price \
  --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev9_grid3_lh.json > results/hol/dev9_grid3_lh.log 2>&1
for S in spider_lh random_lh vijayawada_district; do
  ITMS_SCENARIO=scenarios/generated/$S .venv/bin/python $G --levels heavy --arms hol \
    --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev9_$S.json > results/hol/dev9_$S.log 2>&1
done
.venv/bin/python $G --levels heavy --arms hol --seed-list 101,102,103 --workers 2 --resume \
  --out results/hol/dev9_corridor.json > results/hol/dev9_corridor.log 2>&1
echo done > results/hol/dev9_done.txt
