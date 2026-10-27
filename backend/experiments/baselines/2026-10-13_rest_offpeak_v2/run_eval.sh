#!/usr/bin/env bash
# Held-out run for rest in green as an off-peak mode, second test (TARGETS.md written first).
# Seeds 274-278, light demand. Run from itms/; resumable.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=baselines/2026-10-13_rest_offpeak_v2/results
run() {  # scenario, seeds
  ITMS_SCENARIO=scenarios/generated/$1 .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
    --levels light --arms truth,truth:rest --seed-list $2 --out $R/$1.json > $R/$1.log 2>&1
}
S=274,275,276,277,278
for n in arterial_lh berlin_adlershof grid4_rh_turns spider_lh_tl random_lh grid3_lh ingolstadt narrow_lh amaravati_plan vijayawada_district spider_lh; do
  run $n $S
done
echo done > $R/eval_done.txt
run amaravati_v2 274,275,276
echo done > $R/v2_done.txt
