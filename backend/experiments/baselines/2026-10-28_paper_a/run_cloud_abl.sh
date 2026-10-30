#!/usr/bin/env bash
# Ablation share moved from the Mac to the cloud (2026-10-28). Same arms, seeds and settings as
# run_mac.sh step 3; networks in reverse order so the Mac (forward order) skips what is finished.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
export PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite
R=baselines/2026-10-28_paper_a/results
ABL="truth:c10,truth:nopair,truth:ync,truth:f0,truth:s.gap_out_grace_s=-1,truth:nov,truth:s.cycle_supervisor=false,truth:noovl"
for n in berlin_adlershof grid4_rh_turns random_lh narrow_lh ingolstadt arterial_lh; do
  ITMS_SCENARIO=scenarios/generated/$n python3 scripts/m8_closed_loop_gate.py --workers 2 --resume \
    --levels light,medium,heavy --arms $ABL --seed-list 279,280,281,282,283 --out $R/abl_${n}_ite.json >> $R/abl_${n}_ite.log 2>&1
done
date -u +%FT%TZ > $R/done_cloud_abl.txt
