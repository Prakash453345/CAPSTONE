#!/usr/bin/env bash
# Diagnosis (TRAIN seeds 101-110, no targets): run 4 found the controller 6 % *worse*
# on a 5x4 single-lane grid with 150 m blocks, where CC-A-CAMP does not lock at 0.45.
# Which difference from the 3x3 / 200 m grid matters -- block length or size?
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/hol
for spec in "narrow_grid33_150 grid:3x3,150,1" "narrow_grid54_200 grid:5x4,200,1"; do
  set -- $spec
  [ -f scenarios/generated/$1/scenario.json ] || .venv/bin/python scenarios/build_scenario.py --generate $2 \
    --out scenarios/generated/$1 --name $1 --lefthand --mix india --levels d40:0.40,d45:0.45 --no-cameras > $O/dev30_build_$1.log 2>&1
  ITMS_SCENARIO=scenarios/generated/$1 .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
    --levels d40,d45 --arms truth,hol --seed-list $(seq -s, 101 110) --out $O/dev30_$1.json > $O/dev30_$1.log 2>&1
done
echo done > $O/dev30_done.txt
