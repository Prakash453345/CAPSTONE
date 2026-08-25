#!/usr/bin/env bash
# Generates the two extra demand levels the M4 gate needs [build guide §7:
# "CA-MP beats the tuned fixed-time baseline on person-delay at 3 demand
# levels"] -- "medium" already exists as the project's original
# `vijayawada_corridor.rou.xml` (period 2.5, ~708 vehicles), built by
# `./build.sh` with no args and depended on by every milestone before
# this one. This script produces LIGHT (period 5.0, roughly half the
# volume) and HEAVY (period 1.25, roughly double the volume) as separate,
# suffixed sibling files -- it never touches the medium file.
#
# Periods are not derived from any measured saturation point (this
# project has no calibrated capacity for this corridor -- see
# extract_tier0_config.py's own placeholder-saturation-flow caveat); they
# are a plain 2x/0.5x volume spread around the existing medium demand,
# picked to give three genuinely different, ordered congestion levels to
# compare, not three points chosen to make any particular result look
# better.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

./build.sh 5.0 _light
./build.sh 1.25 _heavy

for suffix in _light _heavy; do
  sed "s/vijayawada_corridor\.rou\.xml/vijayawada_corridor${suffix}.rou.xml/" \
    vijayawada_corridor.sumocfg > "vijayawada_corridor${suffix}.sumocfg"
  echo "done -> vijayawada_corridor${suffix}.sumocfg"
done

echo "Now run assign_vtypes.py against each new .rou.xml (see its own docstring) before use."
