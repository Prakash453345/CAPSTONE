#!/usr/bin/env bash
# Amaravati medium moved from Michael's Mac (51 of 100 records done there: light complete, 1 medium). Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))') PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite
R=baselines/2026-10-29_weak_spots/results
while pgrep -f run_final_cloud.sh > /dev/null; do sleep 30; done
ITMS_SCENARIO=scenarios/generated/amaravati_v2 python3 scripts/m8_closed_loop_gate.py --workers 2 --resume --levels light,medium \
  --arms "truth,truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3,webster:pair,maxpressure,actuated" \
  --seed-list 289,290,291,292,293,294,295,296,297,298 --out $R/final_amaravati_v2_ite.json >> $R/final_amaravati_v2_ite.log 2>&1
date -u +%FT%TZ > $R/done_amaravati_medium.txt
