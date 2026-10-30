#!/usr/bin/env bash
# Combined candidate (careful smart ceiling + kappa_switch=1). TRAINING seeds 101-103. From itms/.
cd "$(dirname "$0")/../../.."
export SUMO_HOME=$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))') PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite
D=baselines/2026-10-29_weak_spots/dev
for n in arterial_lh ingolstadt random_lh grid4_rh_turns narrow_lh; do
  ITMS_SCENARIO=scenarios/generated/$n python3 scripts/m8_closed_loop_gate.py --workers 2 --resume --levels light,medium,heavy \
    --arms "truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3:s.kappa_switch=1" --seed-list 101,102,103 --out $D/combo_${n}.json >> $D/combo_${n}.log 2>&1
done
date -u +%FT%TZ > $D/combo_cloud_done.txt
