-- SAGE schema version 2 — foundation complete (permissions, secrets, memory cognition, audit)

CREATE TABLE IF NOT EXISTS secrets (
    key TEXT PRIMARY KEY,
    ciphertext TEXT NOT NULL,
    salt TEXT NOT NULL,
    nonce TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    rotated_at TEXT
);

CREATE TABLE IF NOT EXISTS permission_grants (
    id TEXT PRIMARY KEY,
    principal TEXT NOT NULL,
    principal_type TEXT NOT NULL DEFAULT 'plugin',
    permission TEXT NOT NULL,
    granted INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    granted_by TEXT DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(principal, permission)
);

CREATE INDEX IF NOT EXISTS idx_perm_principal ON permission_grants(principal);
CREATE INDEX IF NOT EXISTS idx_perm_permission ON permission_grants(permission);

CREATE TABLE IF NOT EXISTS memory_relations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    confidence REAL NOT NULL DEFAULT 0.5,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES memories(id),
    FOREIGN KEY (target_id) REFERENCES memories(id)
);

CREATE INDEX IF NOT EXISTS idx_memrel_source ON memory_relations(source_id);
CREATE INDEX IF NOT EXISTS idx_memrel_target ON memory_relations(target_id);

CREATE TABLE IF NOT EXISTS memory_versions (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    importance REAL,
    confidence REAL,
    metadata TEXT NOT NULL DEFAULT '{}',
    changed_at TEXT NOT NULL,
    change_reason TEXT,
    FOREIGN KEY (memory_id) REFERENCES memories(id)
);

CREATE INDEX IF NOT EXISTS idx_memver_memory ON memory_versions(memory_id);

CREATE TABLE IF NOT EXISTS config_store (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    profile TEXT NOT NULL DEFAULT 'default',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_config_profile ON config_store(profile);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    target TEXT,
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

CREATE TABLE IF NOT EXISTS health_snapshots (
    id TEXT PRIMARY KEY,
    level TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_health_created ON health_snapshots(created_at);

-- Content hash for duplicate detection (nullable for back-compat)
-- SQLite cannot easily ADD COLUMN IF NOT EXISTS across versions; use a safe pattern via migration runner.
