# ADR-001: Evidence-first hexagonal core

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

The engine must add runtimes and model formats without model-specific core branches, while preserving the basis for every capability assertion.

## Decision

Use a dependency-inverted core of immutable domain values and ports. Discovery, inspection, runtime protocols, evaluators, stores, and sandboxes are plugins selected through descriptors. Plugins emit evidence and candidate claims; policy/evaluation determines validation.

## Consequences

- New families normally require data/profile updates, not orchestration changes.
- Plugins are contract-testable with fakes.
- Interchange schemas remain technology-neutral.
- More explicit identities/evidence records are required than in a direct integration.
- A provider declaration can never silently become a validated capability.
