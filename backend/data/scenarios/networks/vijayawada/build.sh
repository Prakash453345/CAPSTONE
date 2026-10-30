#!/usr/bin/env bash
# Reproduces vijayawada_corridor.net.xml from scratch. Run from this directory.
#
# Requires: SUMO_HOME set (pip install eclipse-sumo; see repo README), and
# network access to the OSM Overpass API (osmGet.py hits it directly -- this
# does NOT work from a network-restricted CI/sandbox environment, only from a
# normal machine).
set -euo pipefail

if [ -z "${SUMO_HOME:-}" ]; then
  echo "SUMO_HOME is not set. Example: export SUMO_HOME=\$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')" >&2
  exit 1
fi

BBOX="80.6131,16.4972,80.6586,16.5113"   # Benz Circle <-> PNBS, padded for cross streets
ARTERIAL="MG Road"

echo "1/4  downloading OSM extract for bbox $BBOX ..."
python3 "$SUMO_HOME/tools/osmGet.py" --bbox "$BBOX" -p vijayawada_corridor
mv vijayawada_corridor_bbox.osm.xml raw_osm.xml

echo "2/4  filtering to '$ARTERIAL' + real cross streets ..."
python3 filter_corridor.py raw_osm.xml filtered_corridor.osm.xml --arterial "$ARTERIAL"

echo "3/4  building the SUMO network ..."
# Junctions forced to traffic_light are the 7 highest-degree (4+) real
# crossroads on this corridor -- see README.md "Why these 7 are signalized".
# Regenerate this list (junction degree) if the arterial/bbox changes.
TLS_IDS="cluster_1880441740_4393296791,cluster_1880441532_4393295467_6357870905_6357870906,cluster_11608007559_1880441514_4393295460_6354264758,cluster_1880441541_4393295474,7871074777,2833253632,1880441505"

netconvert --osm-files filtered_corridor.osm.xml -o vijayawada_corridor.net.xml \
  --geometry.remove --geometry.remove.min-length 5 \
  --type-files "$SUMO_HOME/data/typemap/osmNetconvert.typ.xml" \
  --junctions.join --junctions.join-dist 25 \
  --tls.guess-signals --tls.discard-simple --tls.join \
  --roundabouts.guess --ramps.guess \
  --tls.set "$TLS_IDS"

echo "4/4  capping speed limits at the urban-arterial design speed ..."
# netconvert takes its limits from the OSM typemap, which labels this corridor
# 80-100 km/h -- inter-urban defaults on a signalised city arterial. See
# cap_speeds.py for the reasoning and for what reads the limit (the kinematic
# yellow, and timeLoss's free-flow reference).
python3 cap_speeds.py vijayawada_corridor.net.xml

echo "done -> vijayawada_corridor.net.xml"
