#!/usr/bin/env bash
# Paper-A final benchmark, cloud-workspace part (run from itms/, resumable):
# lane-less Indian traffic (sublane copies of two Indian networks), cameras in the
# loop with the adopted detector, and the RL baseline's evaluation. ITE all-red throughout.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
export PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite
R=baselines/2026-10-28_paper_a/results
W=${W:-2}
SEEDS=279,280,281,282,283,284,285,286,287,288
SEEDS5=279,280,281,282,283
g() { ITMS_SCENARIO=scenarios/generated/$1 python3 scripts/m8_closed_loop_gate.py --workers $W --resume \
      --levels light,medium,heavy --arms $2 --seed-list $3 --out $R/$4_$1_ite.json >> $R/$4_$1_ite.log 2>&1; }
# 5. Indian lane-less traffic
for n in arterial_lh_sublane vijayawada_district_sublane; do g $n truth,webster:pair,maxpressure,actuated $SEEDS indian; done
# 6. cameras in the loop, adopted detector (itms6_640, the live service's default), 5 seeds
for n in arterial_lh random_lh; do g $n truth,vision:itms6_640:failsafe $SEEDS5 camera; done
date -u +%FT%TZ > $R/done_cloud.txt
bash baselines/2026-10-28_paper_a/run_cloud_abl.sh
bash baselines/2026-10-28_paper_a/run_cloud_flat.sh
