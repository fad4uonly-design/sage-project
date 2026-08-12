# ADR-007: Sandbox truthfulness and resolver-gated artifact ingestion

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

Part 3 requires production-oriented execution controls and a path from sandbox output to typed evidence. The current environment cannot provide a kernel-enforced container/microVM boundary. A subprocess alone must not be presented as security isolation. Sandbox output also cannot be trusted merely because the sandbox reports a filename or digest.

## Decision

Define `ProductionSandboxBackend` with requested-versus-enforced controls, isolation class, resource/network/filesystem policy, artifact declarations, result capture, and cleanup status.

Provide `ReferenceSubprocessSandbox` only as `REFERENCE_NOT_SECURITY_BOUNDARY`. It demonstrates trusted-harness execution lifecycle and refuses:

- untrusted generated code;
- any mandatory control it cannot actually enforce, including filesystem/network/permission isolation.

All sandbox artifacts must pass `SecureArtifactResolver`. The resolver accepts only declared regular files, rejects symlinks/unexpected files, verifies type/size/reported/expected digests, copies accepted bytes to a private content-addressed store, and reverifies on read. `ProbeArtifactIngestor` additionally binds typed result records to the exact approved plan, run, probe IDs, and subjects.

## Consequences

- Part 3 has production contracts without a false production-isolation claim.
- Live generated-code/probe execution remains blocked until a real production backend is supplied.
- A compromised worker cannot inject arbitrary evidence solely through output files.
- The deterministic backend remains test-only.
