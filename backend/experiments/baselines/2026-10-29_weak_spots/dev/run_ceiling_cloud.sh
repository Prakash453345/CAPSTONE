#!/usr/bin/env bash
# Step 1, ceiling re-tune for the ITE all-red. TRAINING seeds 101-103 only. From itms/.
cd "$(dirname "$0")/../../.."
export SUMO_HOME=$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))') PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite
D=baselines/2026-10-29_weak_spots/dev
ARMS=truth,truth:c1.5:f20,truth:c2:f20,truth:c3:f20,truth:c10:f20,actuated
for n in ingolstadt arterial_lh grid4_rh_turns random_lh narrow_lh berlin_adlershof; do
  ITMS_SCENARIO=scenarios/generated/$n python3 scripts/m8_closed_loop_gate.py --workers 2 --resume --levels light,medium,heavy \
    --arms $ARMS --seed-list 101,102,103 --out $D/ceil_${n}.json >> $D/ceil_${n}.log 2>&1
done
date -u +%FT%TZ > $D/ceil_cloud_done.txt
