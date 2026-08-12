# ADR-002: Separate model, artifact, runtime, and deployment identity

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

Mutable tags, quantization, runtime version/options, and templates can change behavior. Attaching all evidence to a model name would create false provenance.

## Decision

Model, artifact, runtime instance, and model deployment are distinct entities. Behavioral evidence is deployment-scoped and bound to artifact/runtime/adapter/environment digests. Tags and filenames are aliases only.

## Consequences

- The same logical model can have different validated capability records across deployments.
- A changed tag digest invalidates prior deployment evidence instead of inheriting it.
- Deduplication/reconciliation requires explicit evidence.
- Registry entries describe deployable compositions, not model names alone.
