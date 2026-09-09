-- Migration v7: Self-improvement loop (Evolver + SOUP)
-- Applied by sage.db.migrations

-- Evolver variants table: parent/child lineage with immutable mutation tracking
CREATE TABLE IF NOT EXISTS evolver_variants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 0,
    parent_id TEXT,
    payload TEXT NOT NULL,
    mutation TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES evolver_variants(id)
);

CREATE INDEX IF NOT EXISTS idx_evolver_variants_status ON evolver_variants(status);
CREATE INDEX IF NOT EXISTS idx_evolver_variants_parent ON evolver_variants(parent_id);
CREATE INDEX IF NOT EXISTS idx_evolver_variants_generation ON evolver_variants(generation);

-- SOUP runs table: experiment comparison metadata
CREATE TABLE IF NOT EXISTS soup_runs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    eval_set_name TEXT NOT NULL DEFAULT 'builtin',
    baseline_variant_id TEXT NOT NULL,
    winner_variant_id TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL,
    FOREIGN KEY (baseline_variant_id) REFERENCES evolver_variants(id),
    FOREIGN KEY (winner_variant_id) REFERENCES evolver_variants(id)
);

CREATE INDEX IF NOT EXISTS idx_soup_runs_baseline ON soup_runs(baseline_variant_id);
CREATE INDEX IF NOT EXISTS idx_soup_runs_winner ON soup_runs(winner_variant_id);
CREATE INDEX IF NOT EXISTS idx_soup_runs_status ON soup_runs(status);

-- SOUP trials table: per-case scoring for each variant/run
CREATE TABLE IF NOT EXISTS soup_trials (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    score INTEGER NOT NULL,
    response TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES soup_runs(id),
    FOREIGN KEY (variant_id) REFERENCES evolver_variants(id)
);

CREATE INDEX IF NOT EXISTS idx_soup_trials_run ON soup_trials(run_id);
CREATE INDEX IF NOT EXISTS idx_soup_trials_variant ON soup_trials(variant_id);
CREATE INDEX IF NOT EXISTS idx_soup_trials_case ON soup_trials(case_id);

-- Execution audit table (if not already created by previous migration)
CREATE TABLE IF NOT EXISTS execution_audit (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    subject_id TEXT,
    workflow_run_id TEXT,
    skill_id TEXT,
    tool_name TEXT,
    agent_id TEXT,
    principal TEXT,
    status TEXT NOT NULL DEFAULT 'ok',
    summary TEXT,
    reasoning TEXT,
    confidence REAL,
    duration_ms REAL,
    approvals TEXT NOT NULL DEFAULT '[]',
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_audit_kind ON execution_audit(kind);
CREATE INDEX IF NOT EXISTS idx_execution_audit_created ON execution_audit(created_at);
CREATE INDEX IF NOT EXISTS idx_execution_audit_workflow_run ON execution_audit(workflow_run_id);
