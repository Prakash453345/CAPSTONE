#!/usr/bin/env bash
# Step 2a: at heavy demand 86 % of ours' phase changes are pressure switches (grid4 heavy seed 279: 1567 of 1859).
# Hypothesis: the switching cost is too low for the ITE change interval. TRAINING seeds 101-103. From itms/.
cd "$(dirname "$0")/../../.."
export SUMO_HOME=$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))') PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite
D=baselines/2026-10-29_weak_spots/dev
ARMS=truth,truth:s.lost_time_weight=2,truth:s.lost_time_weight=3,truth:s.kappa_switch=1,truth:s.kappa_switch=2
for n in ingolstadt arterial_lh grid4_rh_turns random_lh; do
  ITMS_SCENARIO=scenarios/generated/$n python3 scripts/m8_closed_loop_gate.py --workers 2 --resume --levels heavy,medium \
    --arms $ARMS --seed-list 101,102,103 --out $D/sw_${n}.json >> $D/sw_${n}.log 2>&1
done
date -u +%FT%TZ > $D/sw_done.txt
