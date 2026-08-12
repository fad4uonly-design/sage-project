# ADR-009: Reference approval-gated reversible application manager

- **Status:** Accepted with production limitation
- **Date:** 2026-08-10

## Context

Part 3 requires testable rollback-capable application while explicitly forbidding SAGE integration. Phase 1 states that production application should eventually run as a separate process/credential boundary. The current environment cannot establish that target-specific credential boundary.

## Decision

Implement a target-agnostic `ReversibleApplicationManager` that operates only on an explicitly supplied workspace root and is never invoked by the default lifecycle.

Before writes it verifies:

- exact immutable package approval binding;
- non-blocking security assessment;
- exact change-set digest;
- passing preflight regression;
- per-file before digests.

It snapshots affected files plus declared configuration/registry context into a content-addressed snapshot store, applies files atomically, runs post-application regression, and restores the snapshot on failure. Rollback failures are surfaced as `ROLLBACK_FAILED`; they are never hidden.

The default Part 3 workflow stops after creating a pending human approval request. It never calls this manager. The manager has no SAGE imports, paths, formats, or registry credentials.

## Consequences

- Reversibility and fail-closed behavior are testable now against temporary generic workspaces.
- No claim is made that this library boundary replaces a future separate production applier process.
- SAGE application remains out of scope.
