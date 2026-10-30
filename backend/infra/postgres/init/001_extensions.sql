-- Runs once, on first container init (docker-entrypoint-initdb.d).
-- [ARCH §5.1]: one PostgreSQL instance carries both PostGIS (relational +
-- geospatial: road network, intersections, incidents, dispatches, config,
-- audit) and TimescaleDB (time-series: traffic_stat, fleet AVL history).
-- One engine to operate, not two.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- [ARCH §2.2] Tier-0 safety parameters get their own schema with separate
-- grants — created here, populated starting M2 when the safety kernel lands.
CREATE SCHEMA IF NOT EXISTS safety_config;
