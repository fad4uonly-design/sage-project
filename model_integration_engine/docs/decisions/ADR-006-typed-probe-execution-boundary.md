# ADR-006: Add a typed application-level probe execution boundary

- **Status:** Accepted for Phase 2
- **Date:** 2026-08-10
- **Scope:** implementation specialization; Phase 1 sandbox architecture remains authoritative

## Context

The Phase 1 `SandboxBackend` contract accepts a content-addressed `SandboxJob` and returns attestation plus output artifact **digests**. That is appropriate for a process/container boundary, but the Phase 1 reference contracts do not yet define the artifact-resolver port needed by the Phase 2 coordinator to read and normalize typed per-probe results.

The smallest vertical slice must also be deterministically testable without a live Ollama server or production sandbox.

## Decision

Add an application-level `ProbeExecutionBackend` port in `application/probes.py`. It returns:

- typed, per-probe raw results;
- a sandbox/isolation attestation;
- enforced and missing controls;
- job/backend identity and cleanup/host-write observations.

`SafeProbeHarness` contains only bounded, non-consequential test logic and is intended to execute **inside** a backend boundary. `ProbeCoordinator` refuses to promote any result unless every mandatory control is attested, no host write is observed, and cleanup completes.

No live in-process backend is implemented. Automated tests supply `DeterministicProbeBackend` under `tests/`; it is a test double and any package built from it includes a blocking fixture-only risk.

A future production implementation will adapt `ProbeExecutionBackend` to the Phase 1 `SandboxBackend` plus a content-addressed artifact resolver. That implementation is not part of Phase 2.

## Consequences

- Phase 2 can exercise probe orchestration and failure semantics offline.
- Fixture results cannot be mistaken for live isolation evidence.
- The Phase 1 sandbox contract is not removed or weakened.
- Live behavioral validation remains unavailable until a real sandbox adapter and artifact resolver exist.
- The new narrow port must not become a bypass around the Phase 1 sandbox policy.
