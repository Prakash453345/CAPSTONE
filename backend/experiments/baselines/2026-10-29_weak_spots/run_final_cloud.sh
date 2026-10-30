#!/usr/bin/env bash
# Final test, cloud part: 5 networks + PressLight. Seeds 289-298, ITE. TARGETS.md written first. Resumable. From itms/.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))') PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite
R=baselines/2026-10-29_weak_spots/results; S=289,290,291,292,293,294,295,296,297,298
ARMS="truth,truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3,webster:pair,maxpressure,actuated"
for n in ingolstadt arterial_lh narrow_lh random_lh grid4_rh_turns; do
  ITMS_SCENARIO=scenarios/generated/$n python3 scripts/m8_closed_loop_gate.py --workers 2 --resume --levels light,medium,heavy \
    --arms "$ARMS" --seed-list $S --out $R/final_${n}_ite.json >> $R/final_${n}_ite.log 2>&1
done
[ -f $R/rl_ingolstadt_ite.json ] || for l in light medium heavy; do (cd scripts && ITMS_SCENARIO=../scenarios/generated/ingolstadt \
  python3 paper_a_rl.py eval --level $l --seeds $S --out ../$R/rl_ingolstadt_ite.json >> ../$R/rl_ingolstadt_ite.log 2>&1); done
date -u +%FT%TZ > $R/done_cloud.txt
