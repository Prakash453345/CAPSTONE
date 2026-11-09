#!/usr/bin/env bash
# Paper-A final benchmark, Mac part. From itms/:  bash baselines/2026-10-28_paper_a/run_mac.sh
# Fresh seeds 279-288 (never used before). TARGETS.md was written before any of these runs.
# Resumable: re-running skips finished (arm, level, seed) records.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
export PYTHONHASHSEED=0
export SUMO_BINARY=${SUMO_BINARY:-$PWD/.venv/bin/sumo}  # never a different sumo on PATH
B=baselines/2026-10-28_paper_a
R=$B/results
W=${W:-4}
SEEDS=279,280,281,282,283,284,285,286,287,288
SEEDS5=279,280,281,282,283
NETS="arterial_lh ingolstadt narrow_lh random_lh grid4_rh_turns berlin_adlershof vijayawada_district amaravati_v2"
mkdir -p $R
gate() { # net allred arms seeds tag
  if [ "$2" = ite ]; then export SIGNAL_ALL_RED=ite; else unset SIGNAL_ALL_RED; fi
  ITMS_SCENARIO=scenarios/generated/$1 .venv/bin/python scripts/m8_closed_loop_gate.py --workers $W --resume \
    --levels light,medium,heavy --arms $3 --seed-list $4 --out $R/$5_$1_$2.json >> $R/$5_$1_$2.log 2>&1
}
date -u +%FT%TZ > $R/started_mac.txt
# 1. main table, ITE all-red (the safe version): every controller
for n in $NETS; do gate $n ite truth,webster:pair,maxpressure,actuated $SEEDS main; done
echo "$(date -u +%FT%TZ) main_ite" >> $R/progress_mac.txt
# 2. the same two controllers the earlier results used, on the flat 2.0 s all-red
for n in $NETS; do gate $n flat truth,webster:pair $SEEDS main; done
echo "$(date -u +%FT%TZ) main_flat" >> $R/progress_mac.txt
# 3. ablation, ITE, 5 seeds, one part off at a time (truth comes from step 1)
ABL="truth:c10,truth:nopair,truth:ync,truth:f0,truth:s.gap_out_grace_s=-1,truth:nov,truth:s.cycle_supervisor=false,truth:noovl"
for n in arterial_lh ingolstadt narrow_lh random_lh grid4_rh_turns berlin_adlershof vijayawada_district; do
  gate $n ite $ABL $SEEDS5 abl; done
echo "$(date -u +%FT%TZ) ablation" >> $R/progress_mac.txt
date -u +%FT%TZ > $R/done_mac.txt
