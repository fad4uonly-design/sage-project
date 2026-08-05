-- SAGE schema version 6 — Discovery + UX support tables

CREATE TABLE IF NOT EXISTS discovery_insights (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    evidence TEXT NOT NULL DEFAULT '[]',
    recommendations TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_discovery_created ON discovery_insights(created_at);
CREATE INDEX IF NOT EXISTS idx_discovery_kind ON discovery_insights(kind);
