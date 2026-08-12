# ADR-008: Versioned immutable proposed-package envelope

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

The Phase 1/2 integration-package schema is strict and already used by preserved tests. Part 3 requires additional top-level identities, security assessment, resolver manifest, regression/target/change/rollback digests, immutable submission, and approval binding. Mutating the existing schema in place would weaken reproducibility and risk breaking prior packages.

## Decision

Keep the Phase 1/2 `integration-package.schema.json` as the validated base report and introduce `proposed-integration-package.schema.json` version `0.3.0` as an envelope.

The envelope contains the complete base package plus:

- reconciled composition identity and extension evidence;
- environment and adapter artifact identity;
- resolver-verified artifact manifest;
- security assessment;
- regression, target snapshot, change set, rollback, permission, and policy digests;
- approval binding material;
- immutable content-addressing policy.

`ImmutablePackageStore` validates both layers, checks cross-digests, canonicalizes, hashes, and writes a read-only content-addressed object. An approval event is external and references the immutable package digest to avoid self-referential package hashing.

The capability-registry schema accepts package schema `0.3.0` in addition to historical `0.1.0`.

## Consequences

- Phase 1/2 packages remain valid and tests remain green.
- Part 3 package mutations create a new digest and require new approval.
- Reviewers can inspect both the original evidence report and production lifecycle envelope.
