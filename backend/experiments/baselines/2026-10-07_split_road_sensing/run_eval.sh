#!/usr/bin/env bash
# Held-out run for split-road sensing and rest-in-green (TARGETS.md was written first).
# Seeds 241-245. Run from itms/; resumable.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=baselines/2026-10-07_split_road_sensing/results
S=241,242,243,244,245
run() {  # scenario-or-"-", levels, arms, seeds
  if [ "$1" = "-" ]; then unset ITMS_SCENARIO; n=corridor; else export ITMS_SCENARIO=scenarios/generated/$1; n=$1; fi
  .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume --levels $2 \
    --arms $3 --seed-list $4 --out $R/$n.json > $R/${n}_$2.log 2>&1
}
A3=truth,truth:via2,truth:via2:rest
A2=truth,truth:via2:rest
run amaravati_plan light $A3 $S
run amaravati_plan medium $A3 $S
run vijayawada_district light,medium $A3 $S
run berlin_adlershof light,medium $A3 $S
run grid4_rh_turns light,medium $A3 $S
run ingolstadt light,medium $A3 $S
run arterial_lh light,medium,heavy $A2 $S
run - medium,heavy $A2 $S
run grid3_lh light,medium $A2 $S
run spider_lh light,medium $A2 $S
run random_lh light,medium $A2 $S
run narrow_lh light $A2 $S
run amaravati_plan heavy $A3 $S
echo done > $R/eval_done.txt
run amaravati_v2 light $A3 241,242,243
echo done > $R/v2_done.txt
