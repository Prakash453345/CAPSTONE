#!/usr/bin/env bash
# Amaravati plan grid, training seeds: is the green ceiling what makes light traffic wait?
# A floor under the ceiling (20 s, 30 s) and a ceiling of 3x Webster, against am1's CC-A-CAMP.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/amaravati
for L in light medium heavy; do
ITMS_SCENARIO=scenarios/generated/amaravati_plan .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
  --levels $L --arms truth:f20,truth:f30,truth:c3 --seed-list 101,102,103 --out $O/floor_$L.json > $O/floor_$L.log 2>&1
done
echo done > $O/floor_done.txt
