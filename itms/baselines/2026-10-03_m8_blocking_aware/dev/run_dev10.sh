#!/usr/bin/env bash
# Development (TRAIN seeds 101-103): the final rule (variants only for single-lane approaches).
# Identity checks first, then the three other networks that have single-lane approaches.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d45 --arms hol \
  --seed-list 101,102 --workers 2 --resume --out results/hol/dev10_identity_narrow.json > results/hol/dev10_identity_narrow.log 2>&1
ITMS_SCENARIO=scenarios/generated/grid3_lh .venv/bin/python $G --levels heavy --arms hol \
  --seed-list 101 --workers 1 --resume --out results/hol/dev10_identity_grid3.json > results/hol/dev10_identity_grid3.log 2>&1
.venv/bin/python $G --levels medium,heavy --arms hol --seed-list 101,102,103 --workers 2 --resume \
  --out results/hol/dev10_corridor.json > results/hol/dev10_corridor.log 2>&1
for S in berlin_adlershof vijayawada_district; do
  ITMS_SCENARIO=scenarios/generated/$S .venv/bin/python $G --levels light,heavy --arms hol \
    --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev10_$S.json > results/hol/dev10_$S.log 2>&1
done
echo done > results/hol/dev10_done.txt
