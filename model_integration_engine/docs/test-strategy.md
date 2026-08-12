# Test Strategy

## 1. Objectives

Testing must establish both model behavior and integration safety. A passing answer alone is insufficient; identity, protocol behavior, normalization, isolation, failure handling, provenance, permissions, and reversibility must also be tested.

Test results are evidence records bound to exact model artifact/deployment/runtime/adapter/environment identities.

## 2. Test layers

| Layer | Purpose | Network/model needed? |
|---|---|---|
| Schema tests | Validate interchange documents and invariants | No |
| Domain unit tests | Evidence/support/approval/state invariants | No |
| Plugin contract tests | Every discovery/inspection/adapter plugin conforms | Usually no; use fakes |
| Parser fixture tests | Safe handling of valid/malformed/truncated artifacts | No |
| Adapter protocol tests | Request/response/error/stream normalization | Fake runtime |
| Sandbox policy tests | Controls, denied writes/network, limits, cleanup | Sandbox backend |
| Live runtime tests | Runtime discovery and API behavior | Approved local runtime |
| Behavioral evaluation | Model capabilities under defined profile | Approved deployment |
| Compatibility tests | Target requirements and adapter obligations | Mostly no; uses evidence |
| Regression tests | Existing behavior remains intact | Baseline + candidate |
| Rollback tests | Proposed changes are removable/restorable | Staging only, future phase |

## 3. Phase 1 tests implemented now

- Draft 2020-12 metaschema validation for both JSON Schemas.
- Positive validation of example integration package and registry.
- Negative validation: a capability cannot be `VALIDATED` without `VALIDATED_BY_TEST` evidence.
- Negative validation: an approved package requires complete approval scope metadata.
- Negative validation: active registry entries cannot contain unvalidated capabilities.
- Domain invariant tests for unsupported/unknown/inferred/validated claims.
- Architecture boundary guard: no model-specific or SAGE-specific string/import in core `src/`.
- Reference protocol import and runtime-checkability tests.

These prove contract consistency, not a working model integration.

## 4. Discovery tests

### Contract fixtures

- healthy runtime with zero/one/multiple deployments;
- duplicate aliases pointing to same digest;
- same alias changed to a different digest;
- unavailable/slow/malformed runtime;
- unsupported API version and extra unknown fields;
- approved and unapproved filesystem roots;
- recursive limit, symlink escape, permission error, and race/change during scan;
- valid GGUF, wrong magic, truncated header, huge counts, malformed metadata, shard set.

### Assertions

- no write or model-pull operation occurs;
- observations retain source and collector version;
- aliases do not become identity anchors;
- partial results and retryability are explicit;
- byte/file/time limits are honored;
- unknown fields survive normalization.

## 5. Inspection tests

### GGUF

- header/version/count extraction;
- typed metadata values and arrays;
- architecture-scoped unknown keys;
- tensor table names/shapes/types without reading weights;
- tokenizer IDs/vocabulary/merges presence and digesting;
- chat template extraction;
- quantization distribution and mixed types;
- sidecar/shard relationships;
- malformed length, offset overflow, duplicate key, invalid UTF-8, resource exhaustion.

### Local directories

- allowlisted JSON/text parsing;
- safetensors header-only inspection where implemented;
- executable/pickle files are listed as untrusted but never loaded;
- path traversal/symlink behavior;
- deterministic canonical manifest digest.

### Runtime inspection

- endpoint version and model list/show response;
- missing optional fields;
- capability declaration versus observed API behavior;
- template ownership and raw/runtime templating modes;
- error status and timeout mapping.

## 6. Capability detector tests

Use table-driven observations:

| Observation | Expected claim |
|---|---|
| Runtime declares stream field | Runtime streaming hypothesis, metadata/runtime evidence, unvalidated |
| Successful chunked protocol probe | Runtime streaming validated by test |
| Runtime API accepts tools | Runtime tool-input capability only |
| Model emits correct fake tool call repeatedly | Model tool-calling claim under tested profile |
| No vision field in metadata | Vision remains unknown |
| Explicit unsupported image request plus model/runtime declaration | Negative claim may become not-supported under policy |
| Provider page says “coding” | Inferred/provider hypothesis only |
| Valid JSON once | Test evidence for that trial; reliability threshold may remain unmet |

Property tests should verify no inference-only claim becomes validated and no missing field becomes unsupported.

## 7. Adapter tests

### Request mapping

- role order and typed content parts;
- system prompt ownership;
- tools and JSON Schema mapping;
- response-format/schema mapping;
- think/reasoning preference;
- generation parameters and unsupported parameter failure;
- timeout/cancellation and model reference binding.

### Response mapping

- text, thinking, tool calls, usage, finish reason;
- stream event assembly and ordering;
- unknown fields retained in extension data;
- malformed/partial stream handling;
- runtime error mapping;
- no double template application;
- raw content retention/redaction policy.

The generic adapter contract suite runs unchanged for every compatible deployment.

## 8. Sandbox tests

Tests actively attempt prohibited behavior using a benign adversarial fixture:

- write outside scratch space;
- read target/host paths;
- connect to non-allowlisted endpoints;
- spawn beyond process limit;
- exceed CPU/memory/disk/output/time budget;
- inspect inherited environment secrets;
- leave child processes or files after termination.

Passing functional tests cannot compensate for a failed mandatory sandbox control.

## 9. Behavioral evaluation framework

### 9.1 General rules

- Version every test, rubric, parser, and fixture.
- Prefer machine-checkable outcomes.
- Use multiple trials for stochastic behavior; record seed when supported.
- Fix generation parameters per profile.
- Keep prompts small and non-sensitive.
- Separate capability detection from quality benchmarking.
- Label environment-sensitive metrics.
- Do not score private reasoning traces; score outcomes and exposed protocol fields.

### 9.2 Core suite

**Basic inference**
- health and deterministic canary;
- empty/minimal input behavior;
- bounded output and stop reason.

**Instruction following**
- exact nonce transformation;
- conflicting irrelevant text resistance;
- multi-turn role adherence.

**Reasoning outcome**
- small generated logic/arithmetic tasks with exact answers;
- contamination-resistant parameterized fixtures;
- answer parser and inconclusive handling.

**Structured output**
- valid JSON;
- conformance to nested JSON Schema;
- required fields/types/enums/no extras;
- repeated reliability and malformed request behavior.

**Tool/function calling**
- selects a fake tool only when needed;
- exact function name and argument schema;
- does not fabricate a tool result;
- consumes a fake result and produces a final response;
- declines unavailable/consequential tools safely.

**Context**
- token-count canaries at increasing lengths;
- retrieval at defined positions;
- explicit cap below discovered/runtime resource ceiling;
- truncation/error behavior;
- no claim beyond maximum successfully validated length.

**Reliability and failure**
- repeated trials;
- timeout and cancellation;
- unavailable model/runtime;
- malformed schema/tool request;
- interrupted stream;
- resource pressure within safe limits;
- recovery of next request after failure.

**Latency**
- cold load and warm request separated;
- prompt and generation durations/counts;
- p50/p95 only with sufficient trials;
- hardware/runtime/options captured.

### 9.3 Capability-specific suites

Coding, planning, classification, summarization, embeddings, vision, audio, and domain capabilities are optional plugin suites. A suite is selected only when metadata/runtime evidence creates a hypothesis and required modality fixtures can be handled safely. Absence of a suite leaves the capability unknown.

## 10. Evaluation verdicts

Each test is `PASS`, `FAIL`, `INCONCLUSIVE`, `ERROR`, or `SKIPPED`. Policy turns results into claims:

- one deterministic protocol probe may validate a narrow runtime contract;
- behavioral reliability normally needs repeated passing trials and a configured threshold;
- `ERROR`/`SKIPPED` do not prove unsupported;
- test scope and parameters become capability limitations;
- conflicting tests produce a conflicting or partial claim, not cherry-picked success.

Thresholds are configuration, versioned with the evaluation policy. They must not be hard-coded per model.

## 11. Compatibility tests

For every mandatory target requirement:

1. Find a direct claim with matching subject/scope.
2. If absent, find an adapter obligation and validated adapter contract.
3. Verify limits (context, schema subset, modalities, locality, resources).
4. Verify error/cancellation/stream semantics.
5. Mark unresolved dimensions unknown.

Mutation tests should remove evidence, alter target digest, or change adapter configuration and confirm that compatibility/approval becomes invalid.

## 12. Regression strategy

### Baseline

Capture suite version, target snapshot, environment, current adapters/capabilities, and known failures before candidate evaluation.

### Candidate preflight

Run:

- all mandatory smoke tests;
- generic runtime adapter contract suite;
- new capability tests;
- tests mapped to proposed changes;
- security/permission tests;
- a bounded representative existing regression set.

### Impact report

Report:

- exact proposed changes;
- capabilities added/changed/removed;
- tests selected and why;
- baseline versus candidate outcomes;
- known pre-existing failures;
- flaky/inconclusive results;
- policy blockers.

### Post-application (future)

After approved atomic application, run smoke + affected tests against the active target. Failure triggers the rollback policy and prevents active registry update.

## 13. First vertical slice acceptance criteria

The first Ollama case is successful only if the generic path can:

1. Discover runtime version and deployment using documented read-only APIs.
2. Bind the deployment to a runtime-provided digest, not tag alone.
3. Capture model metadata/template/capability declarations as evidence.
4. Produce separate runtime and model claims.
5. Execute basic chat, stream, schema, tool-call, and failure probes through one generic adapter where supported.
6. Record unsupported/unknown accurately; no capability marketing claims.
7. Run probes through the sandbox port or explicitly block if required controls are unavailable.
8. Produce a schema-valid package at `PROPOSED`/`AWAITING_APPROVAL`.
9. Make no SAGE changes and no active registry entry.
10. Add no model-family branch to core source.

## 14. Evidence proving a phase works

Every phase report must contain:

- source/contract manifest digests;
- exact commands/tests run;
- pass/fail/skipped counts;
- environment/tool versions;
- generated package/schema validation result;
- known limitations and unverified assumptions;
- links/IDs to immutable evidence.

A statement such as “works” without these items is not an accepted phase result.
