#!/usr/bin/env bash
# Demand for the district network (../../networks/vijayawada/vijayawada_district.net.xml),
# the multi-route grid the live console runs on when SIM_NETWORK=district.
# Same method and honesty level as build.sh for the corridor: randomTrips.py
# demand with a fixed seed, not calibrated OD. Three levels (light, medium,
# heavy) so the live service's demand switch works the same on both networks.
#
# The district is about ten times the corridor's road count, so the periods are
# shorter than the corridor's; they were picked so the medium level keeps every
# signal busy without gridlock (checked with a headless run, see README.md).
#
# Usage: SUMO_HOME=... PYTHON=python ./build_district.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
: "${SUMO_HOME:?SUMO_HOME is not set}"
PY="${PYTHON:-python3}"
NET=../../networks/vijayawada/vijayawada_district.net.xml

build() {  # period suffix
  local period="$1" suffix="$2"
  local base="vijayawada_district${suffix}"
  "$PY" "$SUMO_HOME/tools/randomTrips.py" \
    -n "$NET" -o "${base}.trips.xml" --route-file "${base}.rou.xml" \
    -b 0 -e 1800 -p "$period" --fringe-factor 5 --min-distance 300 \
    --validate --seed 42 --vehicle-class passenger --prefix veh
  "$PY" assign_vtypes.py "${base}.rou.xml"
  sed -e "s#vijayawada_corridor\.net\.xml#vijayawada_district.net.xml#" \
      -e "s#vijayawada_corridor\.rou\.xml#${base}.rou.xml#" \
      vijayawada_corridor.sumocfg > "${base}.sumocfg"
  echo "done -> ${base}.rou.xml, ${base}.sumocfg"
}

build "${MEDIUM_PERIOD:-1.0}" ""
build "${LIGHT_PERIOD:-2.0}" _light
build "${HEAVY_PERIOD:-0.5}" _heavy
