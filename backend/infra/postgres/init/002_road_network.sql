-- [ARCH §5.1] Road network reference data lives in PostGIS, in the same
-- Postgres instance as everything else -- not a separate geo database.
-- M1 deliverable: "PostGIS road network from an OSM extract of your chosen
-- area" (build guide). Populated by infra/postgres/import_road_network.py,
-- not by hand -- this file only creates the shape.
--
-- Runs automatically on first container init (fresh volume, via
-- docker-entrypoint-initdb.d). For an existing volume (e.g. anyone who
-- already ran `make dev` for M0), import_road_network.py issues the same
-- CREATE TABLE IF NOT EXISTS statements itself, so it doesn't depend on
-- this file having run.
--
-- One row per scenario network (`network_name`), not one global network --
-- M1 has exactly one (vijayawada_corridor), but nothing here assumes that
-- stays true once city-scale networks arrive (documented future work, see
-- scenarios/networks/vijayawada/README.md).

CREATE TABLE IF NOT EXISTS road_edge (
    id              BIGSERIAL PRIMARY KEY,
    network_name    TEXT NOT NULL,
    sumo_edge_id    TEXT NOT NULL,
    name            TEXT,
    num_lanes       INTEGER NOT NULL,
    speed_limit_mps DOUBLE PRECISION NOT NULL,
    geom            GEOMETRY(LineString, 4326) NOT NULL,
    UNIQUE (network_name, sumo_edge_id)
);

CREATE INDEX IF NOT EXISTS road_edge_geom_idx ON road_edge USING GIST (geom);
CREATE INDEX IF NOT EXISTS road_edge_network_idx ON road_edge (network_name);

CREATE TABLE IF NOT EXISTS road_junction (
    id                BIGSERIAL PRIMARY KEY,
    network_name      TEXT NOT NULL,
    sumo_junction_id  TEXT NOT NULL,
    junction_type     TEXT NOT NULL,
    is_traffic_light  BOOLEAN NOT NULL DEFAULT false,
    geom              GEOMETRY(Point, 4326) NOT NULL,
    UNIQUE (network_name, sumo_junction_id)
);

CREATE INDEX IF NOT EXISTS road_junction_geom_idx ON road_junction USING GIST (geom);
CREATE INDEX IF NOT EXISTS road_junction_network_idx ON road_junction (network_name);
