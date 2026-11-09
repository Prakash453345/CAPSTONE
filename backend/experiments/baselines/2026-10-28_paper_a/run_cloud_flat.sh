#!/usr/bin/env bash
# Flat 2.0 s all-red block from the small end (Preethi's Mac runs it from the large end); resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
export PYTHONHASHSEED=0; unset SIGNAL_ALL_RED
R=baselines/2026-10-28_paper_a/results
for n in arterial_lh ingolstadt narrow_lh random_lh grid4_rh_turns berlin_adlershof; do
  [ -f $R/main_${n}_flat.json ] && python3 -c "import json,sys;sys.exit(0 if len(json.load(open('$R/main_${n}_flat.json'))['records'])>=60 else 1)" && continue
  ITMS_SCENARIO=scenarios/generated/$n python3 scripts/m8_closed_loop_gate.py --workers 2 --resume --levels light,medium,heavy \
    --arms truth,webster:pair --seed-list 279,280,281,282,283,284,285,286,287,288 --out $R/main_${n}_flat.json >> $R/main_${n}_flat.log 2>&1
done
date -u +%FT%TZ > $R/done_cloud_flat.txt
