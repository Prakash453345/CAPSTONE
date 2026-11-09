#!/usr/bin/env bash
# Reproduces the Amaravati capital-complex scenario from scratch. Run from
# this directory. The counterpart of scenarios/networks/vijayawada/build.sh,
# and deliberately the same recipe: one named arterial plus its real cross
# streets, seven forced signals, speeds capped at the urban design limit.
#
# Why this area (80.4616,16.5258 .. 80.4943,16.5573, about 3.5 x 3.5 km):
# it is the only part of the Amaravati extract with named streets end to
# end -- Vijayawada Road running through it as the arterial, crossed by
# Andhra Pradesh High Court Road, Amaravathi Road, Guntur Road,
# Thullur-Velagapudi Road and Seed Access Road. The rest of the planned
# capital is an unnamed grid (N7/N8/E6...), which gives an operator nothing
# to recognise on the map. Chosen by counting distinct named streets in
# every 3.5 km window of the extract; this one won.
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

BBOX="80.4616,16.5258,80.4943,16.5573"
VJW="../../networks/vijayawada"      # the scripts this scenario reuses

echo "1/5  downloading OSM extract for bbox $BBOX ..."
# Unlike the highways-only extract in generated/amaravati/osm/, this one keeps
# amenities -- steps 4 and 5 need the hospitals and police stations.
python3 "$SUMO_HOME/tools/osmGet.py" --bbox "$BBOX" -p amaravati_capital
mv amaravati_capital_bbox.osm.xml raw_osm.xml

echo "2/5  building the SUMO network ..."
# --keep-edges.by-type drops the residential lanes: with them the crop is 1460
# edges of mostly unnamed colony streets, without them it is 86 and reads like
# the corridor. --lefthand because India drives on the left (the Vijayawada
# corridor net predates this and is still right-hand -- see PROGRESS.md).
# --output.street-names carries the OSM names into the net, so the console's
# road pickers show "Vijayawada Road" instead of "Secondary road".
#
# The seven signalised junctions are the crossroads where a named street meets
# the Vijayawada Road arterial, picked by junction degree exactly as the
# corridor's seven were. Regenerate this list if the bbox changes.
TLS_IDS="cluster_2747626025_5823222905_7017737095,cluster_11944253860_11944253868,7896832389,2747625617,2747624839,2747624670,cluster_11944489449_7017737057"

netconvert --osm-files raw_osm.xml -o amaravati_capital.net.xml \
  --keep-edges.in-geo-boundary "$BBOX" \
  --keep-edges.by-type highway.primary,highway.primary_link,highway.secondary,highway.secondary_link,highway.tertiary,highway.tertiary_link,highway.unclassified \
  --type-files "$SUMO_HOME/data/typemap/osmNetconvert.typ.xml" \
  --geometry.remove --geometry.remove.min-length 5 \
  --junctions.join --junctions.join-dist 25 \
  --tls.guess-signals --tls.discard-simple --tls.join \
  --roundabouts.guess --ramps.guess \
  --keep-edges.by-vclass passenger --remove-edges.isolated \
  --junctions.join.parallel-threshold 0 --lefthand \
  --output.street-names true --tls.set "$TLS_IDS"

echo "3/5  capping speed limits at the urban-arterial design speed ..."
python3 "$VJW/cap_speeds.py" amaravati_capital.net.xml

echo "4/5  demand at three levels, plus scenario.json ..."
# Levels are defined by how loaded the busiest junction is (0.25 / 0.5 / 1.0),
# the same targets the corridor measures at, so the two are comparable.
(cd ../../../.. && python3 data/scenarios/build_scenario.py \
  --net data/scenarios/generated/amaravati_capital/amaravati_capital.net.xml \
  --out data/scenarios/generated/amaravati_capital \
  --name amaravati_capital --mix india)

echo "5/5  GeoJSON for the web app, hospitals and police depots ..."
python3 "$VJW/export_geojson.py" amaravati_capital.net.xml amaravati_capital.geojson
python3 - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "../../networks/vijayawada")
import extract_facilities as F, extract_responder_depots as D
net, osm = Path("amaravati_capital.net.xml"), Path("raw_osm.xml")
fac = F.extract(net_path=net, osm_path=osm)
Path("facilities.json").write_text(json.dumps({"facilities": fac}, indent=2))
dep = D.extract(net_path=net, osm_path=osm)
Path("responder_depots.json").write_text(json.dumps({"depots": dep}, indent=2))
print(f"  facilities.json: {len(fac)} hospitals/clinics")
print(f"  responder_depots.json: {len(dep)} depots")
PY

echo "done -> amaravati_capital.net.xml (+ demand, geojson, facilities, depots)"
echo
echo "Cameras need the vision extras installed:"
echo "  python3 ../../../../experiments/m8_plan_cameras.py \\"
echo "      --net amaravati_capital.net.xml --out cameras.json"
echo
echo "Run it:  ITMS_SCENARIO=data/scenarios/generated/amaravati_capital make dev"
