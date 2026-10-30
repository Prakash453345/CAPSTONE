#!/usr/bin/env bash
# Amaravati (planned arterial network from OpenStreetMap, 122 lights): first measurement of
# fixed timing (webster) and CC-A-CAMP (truth) on training seeds. Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
ITMS_SCENARIO=scenarios/generated/amaravati .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
  --levels light,medium,heavy --arms webster,truth --seed-list 101,102,103 \
  --out results/amaravati/base.json > results/amaravati/base.log 2>&1
echo done > results/amaravati/base_done.txt
