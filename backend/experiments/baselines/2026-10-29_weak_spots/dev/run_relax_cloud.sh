#!/usr/bin/env bash
# Step 1b: congestion-adaptive ceiling (+ combination with kappa_switch=1). TRAINING seeds 101-103. From itms/.
cd "$(dirname "$0")/../../.."
export SUMO_HOME=$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))') PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite
D=baselines/2026-10-29_weak_spots/dev
ARMS="truth:s.ceiling_relax_factor=8,truth:s.ceiling_relax_factor=3,truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3,truth:s.ceiling_relax_factor=8:s.kappa_switch=1"
for n in ingolstadt arterial_lh random_lh; do
  ITMS_SCENARIO=scenarios/generated/$n python3 scripts/m8_closed_loop_gate.py --workers 2 --resume --levels light,medium,heavy \
    --arms "$ARMS" --seed-list 101,102,103 --out $D/relax_${n}.json >> $D/relax_${n}.log 2>&1
done
date -u +%FT%TZ > $D/relax_cloud_done.txt
