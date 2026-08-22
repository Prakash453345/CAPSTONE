"""Import a scenario's road network GeoJSON into PostGIS. M1 deliverable
(build guide: "PostGIS road network from an OSM extract of your chosen
area") -- this is the load step; scenarios/networks/<name>/export_geojson.py
is the extract step that produces the file this script reads.

Idempotent: safe to re-run after re-exporting the network (upserts by
(network_name, sumo_edge_id) / (network_name, sumo_junction_id)), and issues
its own `CREATE TABLE IF NOT EXISTS` so it doesn't depend on
infra/postgres/init/002_road_network.sql having run against this particular
Postgres volume (that file only runs automatically on a *fresh* volume;
anyone who already had Postgres running for M0 needs this script to create
the tables itself).

Usage:
    python import_road_network.py \\
        --geojson ../../scenarios/networks/vijayawada/vijayawada_corridor.geojson \\
        --network-name vijayawada_corridor

Requires DATABASE_URL (default: postgresql://itms:itms@localhost:5432/itms,
matching docker-compose.yml) and psycopg[binary] (see requirements-dev.txt).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import psycopg

logging.basicConfig(level=logging.INFO, format="%(asctime)s import-road-network %(message)s")
log = logging.getLogger("import-road-network")

DEFAULT_DATABASE_URL = "postgresql://itms:itms@localhost:5432/itms"

_SCHEMA_SQL = (Path(__file__).resolve().parent / "init" / "002_road_network.sql").read_text()


def _linestring_wkt(coords: list[list[float]]) -> str:
    pts = ", ".join(f"{lon} {lat}" for lon, lat in coords)
    return f"SRID=4326;LINESTRING({pts})"


def _point_wkt(coords: list[float]) -> str:
    lon, lat = coords
    return f"SRID=4326;POINT({lon} {lat})"


def import_network(conn: psycopg.Connection, network_name: str, geojson_path: str) -> dict:
    fc = json.loads(Path(geojson_path).read_text())

    n_edges = n_junctions = 0
    with conn.cursor() as cur:
        cur.execute(_SCHEMA_SQL)

        for feature in fc["features"]:
            props = feature["properties"]
            geom = feature["geometry"]

            if props["kind"] == "edge":
                cur.execute(
                    """
                    INSERT INTO road_edge
                        (network_name, sumo_edge_id, name, num_lanes, speed_limit_mps, geom)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (network_name, sumo_edge_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        num_lanes = EXCLUDED.num_lanes,
                        speed_limit_mps = EXCLUDED.speed_limit_mps,
                        geom = EXCLUDED.geom
                    """,
                    (
                        network_name,
                        props["edge_id"],
                        props["name"],
                        props["num_lanes"],
                        props["speed_limit_mps"],
                        _linestring_wkt(geom["coordinates"]),
                    ),
                )
                n_edges += 1
            elif props["kind"] == "junction":
                cur.execute(
                    """
                    INSERT INTO road_junction
                        (network_name, sumo_junction_id, junction_type, is_traffic_light, geom)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (network_name, sumo_junction_id) DO UPDATE SET
                        junction_type = EXCLUDED.junction_type,
                        is_traffic_light = EXCLUDED.is_traffic_light,
                        geom = EXCLUDED.geom
                    """,
                    (
                        network_name,
                        props["junction_id"],
                        props["junction_type"],
                        props["is_traffic_light"],
                        _point_wkt(geom["coordinates"]),
                    ),
                )
                n_junctions += 1
            else:
                log.warning("skipping feature with unknown kind=%r", props.get("kind"))

    conn.commit()
    return {"edges": n_edges, "junctions": n_junctions}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geojson", required=True, help="path to the exported network GeoJSON")
    parser.add_argument(
        "--network-name",
        required=True,
        help="scenario identifier, e.g. 'vijayawada_corridor' -- rows are keyed by this",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    log.info("connecting to %s", database_url)
    with psycopg.connect(database_url) as conn:
        summary = import_network(conn, args.network_name, args.geojson)
    log.info("imported network=%s: %s", args.network_name, summary)


if __name__ == "__main__":
    main()
