-- [ARCH §2.3] M6: Incident lifecycle, graph adjacency, and conformal
-- calibration state. Same Postgres instance as everything else (§5.1).
-- Runs automatically on first container init (docker-entrypoint-initdb.d).
-- For an existing volume, incident-service issues the same CREATE TABLE
-- IF NOT EXISTS statements itself (same pattern as 002_road_network.sql).

-- Incident state machine: candidate → detected → resolved/rejected
CREATE TABLE IF NOT EXISTS incident (
    id              BIGSERIAL PRIMARY KEY,
    candidate_id    TEXT NOT NULL UNIQUE,
    incident_id     TEXT UNIQUE,
    link_id         TEXT NOT NULL,
    intersection_id TEXT,
    graph_score     DOUBLE PRECISION,
    vision_score    DOUBLE PRECISION,
    fused_score     DOUBLE PRECISION,
    threshold       DOUBLE PRECISION,
    status          TEXT NOT NULL DEFAULT 'candidate',
    confirmed_by    TEXT,
    severity        TEXT DEFAULT 'unknown',
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at    TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    features        JSONB,
    CHECK (status IN ('candidate', 'detected', 'rejected', 'resolved'))
);

CREATE INDEX IF NOT EXISTS incident_status_idx ON incident (status);
CREATE INDEX IF NOT EXISTS incident_link_idx ON incident (link_id);

-- Edge adjacency for the road graph (source → target connectivity).
-- Built from the SUMO net.xml <connection> elements: if edge A has a
-- connection to edge B through any junction, (A, B) is an edge in the
-- graph. This is the adjacency matrix the GNN trains on.
CREATE TABLE IF NOT EXISTS road_edge_adjacency (
    id              BIGSERIAL PRIMARY KEY,
    network_name    TEXT NOT NULL,
    from_edge_id    TEXT NOT NULL,
    to_edge_id      TEXT NOT NULL,
    via_junction_id TEXT,
    UNIQUE (network_name, from_edge_id, to_edge_id)
);

CREATE INDEX IF NOT EXISTS road_edge_adj_network_idx
    ON road_edge_adjacency (network_name);

-- Conformal calibration scores (normal-traffic reference distribution).
-- Each row is one link's fused_score from a pure-normal run, used to
-- compute the conformal threshold τ at target α.
CREATE TABLE IF NOT EXISTS conformal_calibration (
    id          BIGSERIAL PRIMARY KEY,
    link_id     TEXT NOT NULL,
    fused_score DOUBLE PRECISION NOT NULL,
    demand_level TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'offline',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
