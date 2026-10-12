#!/usr/bin/env bash
# Held-out run for the floor under the green ceiling (TARGETS.md was written first).
# Seeds 221-225. Run from itms/; resumable.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=baselines/2026-10-07_ceiling_floor/results
run() {  # scenario-or-"-", levels
  if [ "$1" = "-" ]; then unset ITMS_SCENARIO; n=corridor; else export ITMS_SCENARIO=scenarios/generated/$1; n=$1; fi
  .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume --levels $2 \
    --arms truth,truth:f20 --seed-list 221,222,223,224,225 --out $R/$n.json > $R/$n.log 2>&1
}
run amaravati_plan light,medium,heavy
run arterial_lh light,medium,heavy
run - medium,heavy
run grid3_lh light,medium
run grid4_rh_turns light,medium
run narrow_lh light
run spider_lh light,medium
run random_lh light,medium
run ingolstadt light,medium
run berlin_adlershof light,medium
run vijayawada_district light,medium
echo done > $R/eval_done.txt
