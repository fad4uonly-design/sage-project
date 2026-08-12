# ADR-005: JSON Schema is the normative persistence contract

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

The engine may eventually use multiple languages/processes. A Python-only class model would couple persistence and plugins to one implementation.

## Decision

Use JSON Schema Draft 2020-12 for persisted integration packages and the capability registry. Python dataclasses/protocols are a reference implementation and must not narrow the schema silently.

## Consequences

- Documents can be validated offline across languages.
- Schema/version migrations must be explicit.
- Semantic invariants that JSON Schema cannot express require policy/domain tests.
