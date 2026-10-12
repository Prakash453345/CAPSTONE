#!/usr/bin/env bash
# Development, 30 more TRAIN seeds (111-140; never used before, not EVAL): ten seeds
# could not separate the default from b3 and p0:b3 (dev23: every paired interval
# against the default includes zero). Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
while [ ! -f $O/dev24_done.txt ]; do sleep 15; done
S=$(seq -s, 111 140)
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d30,d35,d40 --arms truth,hol,hol:b3,hol:p0:b3 \
  --seed-list $S --workers 2 --resume --out $O/dev25_sweep.json > $O/dev25_sweep.log 2>&1
echo done > $O/dev25a_done.txt
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d45 --arms hol,hol:b3,hol:p0:b3 \
  --seed-list $(seq -s, 111 130) --workers 2 --resume --out $O/dev25_d45.json > $O/dev25_d45.log 2>&1
echo done > $O/dev25_done.txt
