-- SAGE schema version 3 — Intelligence Layer (Knowledge Graph + learning patterns + capabilities)

CREATE TABLE IF NOT EXISTS kg_entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'concept',
    description TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    source TEXT,
    source_ref TEXT,
    properties TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_entities_canonical
    ON kg_entities(canonical_name) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_kg_entities_name ON kg_entities(name);

CREATE TABLE IF NOT EXISTS kg_edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    confidence REAL NOT NULL DEFAULT 0.5,
    bidirectional INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    source_ref TEXT,
    properties TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    FOREIGN KEY (source_id) REFERENCES kg_entities(id),
    FOREIGN KEY (target_id) REFERENCES kg_entities(id)
);

CREATE INDEX IF NOT EXISTS idx_kg_edges_source ON kg_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_target ON kg_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_relation ON kg_edges(relation);
CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_edges_unique
    ON kg_edges(source_id, target_id, relation) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS kg_entity_versions (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    change_reason TEXT,
    FOREIGN KEY (entity_id) REFERENCES kg_entities(id)
);

CREATE TABLE IF NOT EXISTS kg_edge_versions (
    id TEXT PRIMARY KEY,
    edge_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    change_reason TEXT,
    FOREIGN KEY (edge_id) REFERENCES kg_edges(id)
);

CREATE TABLE IF NOT EXISTS kg_mentions (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    document_id TEXT,
    chunk_id TEXT,
    memory_id TEXT,
    span_text TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    FOREIGN KEY (entity_id) REFERENCES kg_entities(id)
);

CREATE INDEX IF NOT EXISTS idx_kg_mentions_entity ON kg_mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_kg_mentions_document ON kg_mentions(document_id);

CREATE TABLE IF NOT EXISTS learned_patterns (
    id TEXT PRIMARY KEY,
    pattern_type TEXT NOT NULL,
    signature TEXT NOT NULL,
    description TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    confidence REAL NOT NULL DEFAULT 0.3,
    examples TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(pattern_type, signature)
);

CREATE INDEX IF NOT EXISTS idx_patterns_type ON learned_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_patterns_confidence ON learned_patterns(confidence);

CREATE TABLE IF NOT EXISTS capability_registry (
    id TEXT PRIMARY KEY,
    principal TEXT NOT NULL,
    principal_type TEXT NOT NULL DEFAULT 'agent',
    domain TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '[]',
    tools TEXT NOT NULL DEFAULT '[]',
    permissions TEXT NOT NULL DEFAULT '[]',
    reasoning_strategies TEXT NOT NULL DEFAULT '[]',
    confidence_threshold REAL NOT NULL DEFAULT 0.4,
    metadata TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(principal, domain)
);

CREATE INDEX IF NOT EXISTS idx_cap_principal ON capability_registry(principal);
CREATE INDEX IF NOT EXISTS idx_cap_domain ON capability_registry(domain);
