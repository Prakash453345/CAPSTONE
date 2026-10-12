#!/usr/bin/env bash
# Generates a reproducible 30-minute demand file for the Vijayawada corridor
# network. Not calibrated OD (build guide §8.5 -- that's real turning-movement
# counts + GEH validation, done once there's a reason to defend real numbers).
# This is randomTrips.py demand: enough to see actual traffic flow on the
# dashboard for M1's gate ("watch simulated traffic move... at 1 Hz"), fixed
# seed so every run is the same run.
#
# Optional args, added for M4's "3 demand levels" gate requirement without
# disturbing the plain `./build.sh` invocation every earlier milestone
# already depends on: `./build.sh [period] [suffix]`. With no args this
# reproduces exactly the original medium-demand file (period 2.5, no
# suffix). `build_demand_levels.sh` calls this with light/heavy periods
# and suffixes to produce sibling files rather than overwriting it.
set -euo pipefail

if [ -z "${SUMO_HOME:-}" ]; then
  echo "SUMO_HOME is not set." >&2
  exit 1
fi

PERIOD="${1:-2.5}"
SUFFIX="${2:-}"

python3 "$SUMO_HOME/tools/randomTrips.py" \
  -n ../../networks/vijayawada/vijayawada_corridor.net.xml \
  -o "vijayawada_corridor${SUFFIX}.trips.xml" \
  --route-file "vijayawada_corridor${SUFFIX}.rou.xml" \
  -b 0 -e 1800 -p "$PERIOD" --fringe-factor 5 --validate --seed 42 \
  --vehicle-class passenger --prefix veh

echo "done -> vijayawada_corridor${SUFFIX}.rou.xml"
