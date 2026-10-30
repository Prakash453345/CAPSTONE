#!/usr/bin/env bash
# v2 fresh-seed test, Michael's Mac part: amaravati_v2 light + medium, seeds 299-308. TARGETS.md written first.
# From itms/:  bash baselines/2026-10-30_adaptive_ceiling_v2/run_mac.sh      (resumable)
cd "$(dirname "$0")/../.."
export SUMO_BINARY=$PWD/.venv/bin/sumo SIGNAL_ALL_RED=ite PYTHONHASHSEED=0
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
A="truth,truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3:s.ceiling_relax_hold_s=900,webster:pair,maxpressure,actuated"
ITMS_SCENARIO=scenarios/generated/amaravati_v2 caffeinate -i .venv/bin/python scripts/m8_closed_loop_gate.py --workers 4 --resume \
  --levels light,medium --arms "$A" --seed-list 299,300,301,302,303,304,305,306,307,308 \
  --out baselines/2026-10-30_adaptive_ceiling_v2/results/final_amaravati_v2_ite.json
