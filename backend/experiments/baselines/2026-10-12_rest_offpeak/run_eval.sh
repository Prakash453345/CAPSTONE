#!/usr/bin/env bash
# Held-out run for rest in green as an off-peak mode (TARGETS.md was written first).
# Seeds 264-268, light demand. Run from itms/; resumable.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=baselines/2026-10-12_rest_offpeak/results
run() {  # scenario, seeds
  ITMS_SCENARIO=scenarios/generated/$1 .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
    --levels light --arms truth,truth:rest --seed-list $2 --out $R/$1.json > $R/$1.log 2>&1
}
S=264,265,266,267,268
for n in arterial_lh berlin_adlershof grid4_rh_turns spider_lh random_lh grid3_lh ingolstadt narrow_lh amaravati_plan vijayawada_district; do
  run $n $S
done
echo done > $R/eval_done.txt
run amaravati_v2 264,265,266
echo done > $R/v2_done.txt
