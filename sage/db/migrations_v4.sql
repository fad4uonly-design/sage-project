-- SAGE schema version 4 — Automation (workflows, approvals, audit, automation jobs)

CREATE TABLE IF NOT EXISTS workflow_definitions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0.0',
    description TEXT,
    definition TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id TEXT PRIMARY KEY,
    definition_id TEXT NOT NULL,
    status TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '{}',
    current_step TEXT,
    checkpoint TEXT NOT NULL DEFAULT '{}',
    result TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    principal TEXT NOT NULL DEFAULT 'core',
    parent_run_id TEXT,
    FOREIGN KEY (definition_id) REFERENCES workflow_definitions(id)
);

CREATE INDEX IF NOT EXISTS idx_wf_runs_status ON workflow_runs(status);
CREATE INDEX IF NOT EXISTS idx_wf_runs_def ON workflow_runs(definition_id);

CREATE TABLE IF NOT EXISTS workflow_step_runs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    input TEXT NOT NULL DEFAULT '{}',
    output TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (run_id) REFERENCES workflow_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_wf_steps_run ON workflow_step_runs(run_id);

CREATE TABLE IF NOT EXISTS approval_policies (
    id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'ask_once',
    principal TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(resource_type, resource_id, principal)
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    action TEXT NOT NULL,
    level TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    principal TEXT NOT NULL DEFAULT 'user',
    reason TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    decided_by TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status);

CREATE TABLE IF NOT EXISTS execution_audit (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    subject_id TEXT,
    workflow_run_id TEXT,
    skill_id TEXT,
    tool_name TEXT,
    agent_id TEXT,
    principal TEXT,
    status TEXT NOT NULL,
    summary TEXT,
    reasoning TEXT,
    confidence REAL,
    duration_ms REAL,
    approvals TEXT NOT NULL DEFAULT '[]',
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_kind ON execution_audit(kind);
CREATE INDEX IF NOT EXISTS idx_audit_created ON execution_audit(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_run ON execution_audit(workflow_run_id);

CREATE TABLE IF NOT EXISTS automation_jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    trigger_type TEXT NOT NULL,
    trigger_config TEXT NOT NULL DEFAULT '{}',
    workflow_id TEXT,
    skill_id TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at TEXT,
    last_status TEXT,
    run_count INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auto_jobs_enabled ON automation_jobs(enabled);
