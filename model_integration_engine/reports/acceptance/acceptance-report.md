# Real Deployment Acceptance Report

**Lifecycle state:** `DRAFT_PENDING_APPROVAL`
**Approval state:** `NOT_REQUESTED`
**Approval request created:** `false`
**Runtime endpoint:** `http://localhost:11434`
**Runtime model reference:** `qwen3:4b`
**Security verdict:** `BLOCKED`

## USER-SUPPLIED EVIDENCE

Records: **0**. These records retain `kind=USER_INPUT` and are not behavioral validation.

## LIVE RUNTIME EVIDENCE

Records: **55** from the generic Ollama `/api/version`, `/api/tags`, and `/api/show` path. Responses are bound to source digests in `live-runtime-evidence.json`.

## ARTIFACT EVIDENCE

Status: `NOT_SUPPLIED`. Declared context or feature metadata is not promoted to usable behavioral capability.

## BEHAVIORAL TEST EVIDENCE

Status: `BLOCKED_PRODUCTION_SANDBOX_UNAVAILABLE`. Planned probes blocked: **8**. The reference subprocess backend was not used and no production-isolation claim was made.

## INFERRED CAPABILITIES

Metadata/runtime declarations remain hypotheses unless backed by passing `VALIDATED_BY_TEST` evidence. See `capability-assessment.json`.

## UNKNOWN/BLOCKED CAPABILITIES

Basic generation, deterministic instruction behavior, streaming, bounded context, structured output, tool calling, error handling, and timeout handling remain blocked for MIE-controlled validation in this run.

## Compatibility

Overall status: `UNKNOWN`. Unknown mandatory requirements remain fail-closed.

## Capability delta

Status: `UNKNOWN_NO_REGISTRY_SNAPSHOT`. The registry was read-only and was not modified.

## Draft package

Immutable package digest: `sha256:fb263d3b91afae9c25977080a9933d4123c7c90e0a7ac759a918d0eb29cebc81`. The package remains `DRAFT_PENDING_APPROVAL`; no approval, application, SAGE access, or global registration occurred.
