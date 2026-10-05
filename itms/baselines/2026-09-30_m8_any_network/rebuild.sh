#!/usr/bin/env bash
# Rebuilds every scenario of this baseline exactly (the trip periods recorded in
# each scenario.json; the vehicles come out identical). Run from itms/ with
# SUMO_HOME set. The networks are rebuilt too: generated ones by netgenerate,
# the two cities copied from SUMO's own examples.
set -euo pipefail
S=$SUMO_HOME/tools/game

python scenarios/build_scenario.py --generate grid:3x3,300,2 --lefthand --mix india \
    --periods light:2.245,medium:1.052,heavy:0.4972 --out scenarios/generated/grid3_lh
python scenarios/build_scenario.py --generate grid:6x1,300,3,200 --lefthand --tls-layout incoming --mix india \
    --periods light:4.9457,medium:2.4029,heavy:1.2364 --out scenarios/generated/arterial_lh
python scenarios/build_scenario.py --generate grid:3x3,200,1 --lefthand --mix india \
    --periods light:2.0613,medium:0.9973,heavy:0.4792 --out scenarios/generated/narrow_lh
python scenarios/build_scenario.py --generate spider:5,3,200,2 --lefthand --mix india --no-cameras \
    --periods light:2.0087,medium:1.0043,heavy:0.5149 --out scenarios/generated/spider_lh
python scenarios/build_scenario.py --generate rand:40,200,2,3 --lefthand --mix india --no-cameras \
    --periods light:4.2575,medium:2.0828,heavy:0.9996 --out scenarios/generated/random_lh
python scenarios/build_scenario.py --generate grid:4x4,250,2 --turn-lanes 1 --tls-layout incoming --mix cars \
    --periods light:2.6839,medium:1.2801,heavy:0.621 --out scenarios/generated/grid4_rh_turns
python scenarios/build_scenario.py --net $S/DRT/osm.net.xml --name berlin_adlershof --mix cars \
    --periods light:3.646,medium:1.6586,heavy:0.764 --out scenarios/generated/berlin_adlershof
python scenarios/build_scenario.py --net $S/fkk_in/ingolstadt.net.xml.gz --name ingolstadt --mix cars --no-cameras \
    --periods light:4.7263,medium:2.3006,heavy:1.1816 --out scenarios/generated/ingolstadt
# the district, from the raw OSM extract of the corridor's box downloaded on
# 2026-08-21 (vijayawada_corridor_bbox.osm.xml, 7.5 MB, md5
# 22fa4a502a30e373ee17b03ecf10ccc2; not committed). A new download of the
# box (networks/vijayawada/build.sh step 1) will differ as OSM is edited.
python scenarios/city_from_osm.py --osm vijayawada_corridor_bbox.osm.xml \
    --crop 80.6131,16.4972,80.6586,16.5113 --name vijayawada_district --lefthand --no-cameras \
    --periods light:3.3928,medium:1.6964,heavy:0.9063
