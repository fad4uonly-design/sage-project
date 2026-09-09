-- Migration v8: audit subsystem discriminator
-- Applied by sage.db.migrations
--
-- Step 0 of the provider-wiring pass found: execution_audit has a `kind`
-- column ("approval" / "system" / ...) but NOTHING distinguishing which
-- subsystem wrote an approval entry — Evolver (kind="system"), the Phase 3
-- model gate (kind="approval") and the Phase 4 code gate (kind="approval")
-- all share one table. Add an additive `subsystem` column; writers set it
-- explicitly, old rows keep "unknown".
ALTER TABLE execution_audit ADD COLUMN subsystem TEXT NOT NULL DEFAULT 'unknown';

CREATE INDEX IF NOT EXISTS idx_execution_audit_subsystem ON execution_audit(subsystem);
