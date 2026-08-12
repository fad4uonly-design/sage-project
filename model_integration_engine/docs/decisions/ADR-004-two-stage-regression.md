# ADR-004: Two-stage regression

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

Regression must gate integration, yet active-state verification is also required after application.

## Decision

Run candidate/baseline regression in staging before approval/application, then run smoke and affected regression after a future atomic application. Registry activation occurs only after post-application verification. A post-application failure invokes rollback policy.

## Consequences

- No change is approved without preflight evidence.
- Deployment-specific failures can still be detected before registration.
- Test identities must bind baseline, candidate, and environment.
