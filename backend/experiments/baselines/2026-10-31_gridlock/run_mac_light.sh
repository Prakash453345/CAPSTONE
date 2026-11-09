#!/usr/bin/env bash
# v3 fresh-seed test, Mac part. Usage (from the backend folder):  NETS="amaravati_v2" bash experiments/baselines/2026-10-31_gridlock/run_mac.sh
# Resumable: run the same command again after any stop.
cd "$(dirname "$0")/../../.."
export PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite SUMO_BINARY=.venv/bin/sumo
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=experiments/baselines/2026-10-31_gridlock/results; S=309,310,311,312,313,314,315,316,317,318
V3='truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3:s.ceiling_relax_hold_s=900:s.ceiling_relax_net_block=0.7:s.ceiling_relax_net_signal=max:s.ceiling_relax_net_halflife_s=60:s.ceiling_relax_net_release_s=1800:s.ceiling_relax_warmup_s=750'
ARMS="actuated,maxpressure,webster:pair"
mkdir -p $R
for n in $NETS; do
  ITMS_SCENARIO=data/scenarios/generated/$n caffeinate -i .venv/bin/python experiments/m8_closed_loop_gate.py --workers ${WORKERS:-4} --resume \
    --levels light --arms "$ARMS" --seed-list $S --out $R/final_${n}_light_mac_ite.json 2>&1 | tee -a $R/final_${n}_light_mac_ite.log | grep --line-buffered -E "^\[|runs to do|wrote|Error"
done
