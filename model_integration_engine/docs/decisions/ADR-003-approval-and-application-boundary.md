# ADR-003: Approval and application are a separate boundary

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

Generated adapters and self-improvement plans cannot safely authorize or apply their own changes. Phase 1 must not modify SAGE.

## Decision

MIE stops at a content-addressed proposal. Human approval binds package, change set, target snapshot, permissions, policy, and rollback digests. A future applier will be a separate process and credential boundary. No application protocol or SAGE write implementation exists in Phase 1 source.

## Consequences

- Test success cannot trigger integration.
- Material changes invalidate approval.
- Reversibility and exact write sets are package requirements.
- An extra future component is necessary, but accidental coupling/write access is reduced.
