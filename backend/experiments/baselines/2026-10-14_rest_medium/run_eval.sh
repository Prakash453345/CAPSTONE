#!/usr/bin/env bash
# Held-out run, rest in green at medium demand (TARGETS.md written first). Run from itms/; resumable.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=baselines/2026-10-14_rest_medium/results
for n in arterial_lh grid4_rh_turns grid3_lh random_lh berlin_adlershof amaravati_plan spider_lh_tl ingolstadt; do
  ITMS_SCENARIO=scenarios/generated/$n .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
    --levels medium --arms truth,truth:rest --seed-list 279,280,281,282,283 --out $R/$n.json > $R/$n.log 2>&1
done
echo done > $R/eval_done.txt
