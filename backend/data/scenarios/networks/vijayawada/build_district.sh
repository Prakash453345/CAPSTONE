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
# Busy routes beyond the district: trunk, primary and secondary roads from this larger
# extract (district_busy.osm.xml, from the Overpass API) are added out to MARGIN
# degrees (0.03 is about 3 km) past BOX, the district's own extent. Without
# the file the district is exactly what RAW holds.
BUSY="${BUSY:-district_busy.osm.xml}"
BOX="${BOX:-80.610982,16.485617,80.674690,16.520437}"
MARGIN="${MARGIN:-0.03}"
# Streets taken whole that join the district to a place it must reach: the
# Gurunanak Colony road east to the Agni Mapaka Kendram fire station
# (district_extra.osm.xml, from OpenStreetMap). Without it the station is 1.4 km
# beyond the network's end.
EXTRA="${EXTRA:-district_extra.osm.xml}"
ADD=()
[ -f "$EXTRA" ] && ADD=(--add "$EXTRA")
EXTEND=()
[ -f "$BUSY" ] && EXTEND=(--extend "$BUSY" --box "$BOX" --margin "$MARGIN")

# No --tls.join (the corridor build uses it): it can merge two nearby crossings
# into one signal program spanning two junctions, and the Tier-0 extractor and
# the arbiter model one signal per junction.
# --lefthand: India drives on the left (SUMO defaults to right-hand traffic).
# Also passed to the two --sumo-net-file passes below so it is never dropped.
osm_opts=(
  --lefthand
  --geometry.remove --geometry.remove.min-length 5
  --type-files "$SUMO_HOME/data/typemap/osmNetconvert.typ.xml"
  --junctions.join --junctions.join-dist 25
  --tls.guess-signals --tls.discard-simple
  --roundabouts.guess --ramps.guess
  --output.street-names
  --keep-edges.components 1 --remove-edges.isolated
)

echo "1/6  filtering $RAW to the arterial grid ..."
"$PY" filter_district.py "$RAW" filtered_district.osm.xml ${ADD[@]+"${ADD[@]}"} "${EXTEND[@]}"

echo "2/6  survey build: find the connected core and the arterial crossings ..."
netconvert --osm-files filtered_district.osm.xml -o district_survey.net.xml "${osm_opts[@]}"
"$PY" select_district.py ${EXTEND[@]+--extension filtered_district.osm.xml.extension} district_survey.net.xml district_keep_edges.txt district_tls.txt

echo "3/6  build with the crossings signalised ..."
# --tls.set applies before --junctions.join, so a joined junction
# ("cluster_A_B_C") is named by the OSM nodes it is made of: A,B,C.
TLS_NODES="$(sed -e 's/cluster_//g' -e 's/_/,/g' district_tls.txt)"
netconvert --osm-files filtered_district.osm.xml -o district_signalised.net.xml \
  "${osm_opts[@]}" --tls.set "$TLS_NODES"

echo "4/6  trimming to the strongly connected core ..."
# On a finished network the edge ids are final, so the core list (taken from
# the survey build, which merges geometry the same way) matches exactly.
netconvert --sumo-net-file district_signalised.net.xml -o vijayawada_district.net.xml --lefthand --tls.rebuild \
  --keep-edges.input-file district_keep_edges.txt --output.street-names

# A few joined crossings are not addressable by their OSM nodes on the OSM
# pass; on the finished network their cluster ids are final, so signalise the
# remainder there (only those -- re-setting an existing signal aborts).
MISSING="$("$PY" select_district.py --missing vijayawada_district.net.xml - district_tls.txt | tr -d '
')"
if [ -n "$MISSING" ]; then
  netconvert --sumo-net-file vijayawada_district.net.xml -o district_final.net.xml --lefthand --tls.set "$MISSING" --output.street-names
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
