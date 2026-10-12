#!/usr/bin/env bash
# Reproduces vijayawada_district.net.xml -- the multi-route district network --
# from the same raw OSM extract as the corridor. Run from this directory.
#
# The corridor (build.sh) is one arterial on purpose and is what the M4-M7
# gates and benchmarks measure; it is untouched by this script. The district
# keeps the whole arterial grid around it so emergency routing has real
# alternatives to choose between. See README.md "District network".
#
# Requires SUMO_HOME (pip install eclipse-sumo) and the raw OSM extract from
# step 1 of build.sh (the repo-root vijayawada_corridor_bbox.osm.xml is the
# same file). Usage: ./build_district.sh [raw_osm.xml]
set -euo pipefail

if [ -z "${SUMO_HOME:-}" ]; then
  echo "SUMO_HOME is not set. Example: export SUMO_HOME=\$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')" >&2
  exit 1
fi
PY="${PYTHON:-python3}"
RAW="${1:-raw_osm.xml}"

# No --tls.join (the corridor build uses it): it can merge two nearby crossings
# into one signal program spanning two junctions, and the Tier-0 extractor and
# the arbiter model one signal per junction.
osm_opts=(
  --geometry.remove --geometry.remove.min-length 5
  --type-files "$SUMO_HOME/data/typemap/osmNetconvert.typ.xml"
  --junctions.join --junctions.join-dist 25
  --tls.guess-signals --tls.discard-simple
  --roundabouts.guess --ramps.guess
  --output.street-names
  --keep-edges.components 1 --remove-edges.isolated
)

echo "1/6  filtering $RAW to the arterial grid ..."
"$PY" filter_district.py "$RAW" filtered_district.osm.xml

echo "2/6  survey build: find the connected core and the arterial crossings ..."
netconvert --osm-files filtered_district.osm.xml -o district_survey.net.xml "${osm_opts[@]}"
"$PY" select_district.py district_survey.net.xml district_keep_edges.txt district_tls.txt

echo "3/6  build with the crossings signalised ..."
# --tls.set applies before --junctions.join, so a joined junction
# ("cluster_A_B_C") is named by the OSM nodes it is made of: A,B,C.
TLS_NODES="$(sed -e 's/cluster_//g' -e 's/_/,/g' district_tls.txt)"
netconvert --osm-files filtered_district.osm.xml -o district_signalised.net.xml \
  "${osm_opts[@]}" --tls.set "$TLS_NODES"

echo "4/6  trimming to the strongly connected core ..."
# On a finished network the edge ids are final, so the core list (taken from
# the survey build, which merges geometry the same way) matches exactly.
netconvert --sumo-net-file district_signalised.net.xml -o vijayawada_district.net.xml \
  --keep-edges.input-file district_keep_edges.txt --output.street-names

# A few joined crossings are not addressable by their OSM nodes on the OSM
# pass; on the finished network their cluster ids are final, so signalise the
# remainder there (only those -- re-setting an existing signal aborts).
MISSING="$("$PY" select_district.py --missing vijayawada_district.net.xml - district_tls.txt | tr -d '
')"
if [ -n "$MISSING" ]; then
  netconvert --sumo-net-file vijayawada_district.net.xml -o district_final.net.xml     --tls.set "$MISSING" --output.street-names
  mv district_final.net.xml vijayawada_district.net.xml
fi

echo "5/6  capping speed limits at the urban design speed ..."
"$PY" cap_speeds.py vijayawada_district.net.xml

echo "6/6  verifying ..."
"$PY" select_district.py --verify vijayawada_district.net.xml district_keep_edges.txt district_tls.txt
rm -f district_survey.net.xml district_signalised.net.xml

# the console's map geometry (web-app, VITE_ITMS_NETWORK=district)
"$PY" export_geojson.py vijayawada_district.net.xml vijayawada_district.geojson

echo "done -> vijayawada_district.net.xml, vijayawada_district.geojson"
echo "demand: ../../demand/vijayawada/build_district.sh"
