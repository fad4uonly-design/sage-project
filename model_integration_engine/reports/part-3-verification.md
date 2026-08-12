# Model Integration Engine — Part 3 Verification Report

**Date:** 2026-08-10
**Version:** 0.3.0a0
**Scope:** production-oriented generic lifecycle infrastructure; no SAGE integration
**Default terminal state:** `DRAFT_PENDING_APPROVAL`

## 1. Completion summary

Part 3 extends the preserved Phase 1/2 path with:

- production-oriented sandbox and policy contracts;
- a truthfully limited reference subprocess backend;
- resolver-gated, typed artifact ingestion;
- bounded generic GGUF/tensor inspection;
- generic tokenizer and static chat-template inspection;
- runtime plugin registration/selection;
- durable content/deployment/composition identity reconciliation;
- expanded behavioral capability probes;
- layered adapter resolution and untrusted generated proposals;
- structured security assessment;
- immutable proposed-package submission;
- exact approval binding;
- generic rollback-capable application behind approval;
- fail-closed before/after regression comparison;
- evidence/approval/regression-gated capability registration;
- end-to-end orchestration through pending human approval, then stop.

The default workflow does not call application, rollback, post-application regression, or registry update.

## 2. Test and compile result

Command:

```bash
python3 -m pytest -q
```

Result:

```text
78 passed, 1 skipped in 7.50s
```

The single skip is the preserved opt-in live Ollama test because no endpoint/model was configured. All Phase 1 and Phase 2 tests remain in the suite and pass.

Compilation:

```text
python3 -m compileall -q src tests
compileall: PASS
```

Boundary scans:

```text
model-specific production logic: NONE
SAGE dependency: NONE
```

Artifact integrity:

```text
reports/part-3-artifact-manifest.sha256
106 files
verification: PASS
```

## 3. Part 3 tests added

### GGUF, tensors, tokenizer, templates

`tests/test_phase3_gguf.py`

- unknown architecture without crash;
- GGUF version/count/metadata extraction;
- observed tensor names/shapes/types/quantization;
- interpreted parameter estimate separated from observed shapes;
- unknown tensor type preservation;
- unknown metadata preservation;
- corrupted magic, truncated header, unsupported version;
- tokenizer vocabulary/special token/BOS/EOS/padding/type/merges variants;
- missing tokenizer/template remains unknown;
- static template/tool hints remain unvalidated.

### Sandbox and artifacts

`tests/test_phase3_sandbox_artifacts.py`

- reference backend refuses untrusted code and missing controls;
- controlled trusted-harness execution, limits, capture, collection, cleanup;
- resolver digest/type/provenance validation;
- artifact tampering, unexpected injection, and stored-object tampering rejection;
- typed probe artifact binding to exact plan/run/probe/subject.

### Runtime, identity, adapters, expanded probes

`tests/test_phase3_runtime_identity_adapter.py`

- runtime plugin registration, duplicate and missing plugin handling;
- alias collision with different content digests;
- stable logical content identity and environment-scoped composition identity;
- existing/configurable adapter preference;
- untrusted, non-executable generated adapter proposal;
- generated proposal rejection on a non-production sandbox;
- bounded context and declared multimodal behavior validated only by passing probes.

### Proposed package and approval

`tests/test_phase3_package_approval_workflow.py`

- end-to-end pending-approval stop;
- proposed and embedded base schema validation;
- blocking security assessment when resolver evidence is missing;
- immutable store verification;
- pre-submission mutation rejection;
- post-submission tamper detection;
- approval invalidation after package change;
- non-human approval rejection.

### Rollback, regression, registry

`tests/test_phase3_rollback_regression_registry.py`

- functional/capability/compatibility/configuration/risk comparison;
- mandatory failure closes regression;
- target/configuration/registry snapshot capture;
- post-application regression-triggered rollback;
- rollback failure surfaced as `ROLLBACK_FAILED`;
- approved, security-eligible, regression-passing validated registration;
- unvalidated capability and failed regression rejection.

## 4. Complete source module inventory

```text
src/model_integration_engine/__init__.py
src/model_integration_engine/domain.py
src/model_integration_engine/contracts.py
src/model_integration_engine/evidence.py
src/model_integration_engine/phase2_models.py
src/model_integration_engine/live_validation.py

src/model_integration_engine/adapters/__init__.py
src/model_integration_engine/adapters/engine.py

src/model_integration_engine/application/__init__.py
src/model_integration_engine/application/changes.py
src/model_integration_engine/application/lifecycle.py
src/model_integration_engine/application/probes.py
src/model_integration_engine/application/vertical_slice.py

src/model_integration_engine/approval/__init__.py
src/model_integration_engine/approval/binding.py

src/model_integration_engine/capabilities/__init__.py
src/model_integration_engine/capabilities/hypotheses.py

src/model_integration_engine/compatibility/__init__.py
src/model_integration_engine/compatibility/evaluator.py

src/model_integration_engine/identity/__init__.py
src/model_integration_engine/identity/reconciliation.py

src/model_integration_engine/inspectors/__init__.py
src/model_integration_engine/inspectors/gguf.py
src/model_integration_engine/inspectors/tokenizer.py
src/model_integration_engine/inspectors/template.py

src/model_integration_engine/packaging/__init__.py
src/model_integration_engine/packaging/draft.py
src/model_integration_engine/packaging/proposed.py

src/model_integration_engine/plugins/__init__.py
src/model_integration_engine/plugins/ollama/__init__.py
src/model_integration_engine/plugins/ollama/client.py
src/model_integration_engine/plugins/ollama/discovery.py
src/model_integration_engine/plugins/ollama/inspection.py
src/model_integration_engine/plugins/ollama/adapter.py

src/model_integration_engine/registry/__init__.py
src/model_integration_engine/registry/capability_registry.py

src/model_integration_engine/regression/__init__.py
src/model_integration_engine/regression/framework.py

src/model_integration_engine/runtimes/__init__.py
src/model_integration_engine/runtimes/base.py
src/model_integration_engine/runtimes/registry.py
src/model_integration_engine/runtimes/ollama.py

src/model_integration_engine/sandbox/__init__.py
src/model_integration_engine/sandbox/contracts.py
src/model_integration_engine/sandbox/reference.py
src/model_integration_engine/sandbox/artifacts.py
src/model_integration_engine/sandbox/probe_artifacts.py

src/model_integration_engine/security/__init__.py
src/model_integration_engine/security/assessment.py
```

New/updated contract artifacts:

```text
schemas/proposed-integration-package.schema.json
schemas/capability-registry.schema.json
schemas/integration-package.schema.json (preserved base)

docs/decisions/ADR-007-sandbox-truthfulness-and-artifact-gate.md
docs/decisions/ADR-008-versioned-proposed-package-envelope.md
docs/decisions/ADR-009-reference-approval-gated-application.md

reports/samples/part3-proposed-integration-package.json
reports/samples/part3-approval-request.json
reports/samples/part3-capability-registry.example.json
reports/samples/part3-evidence-chain.example.json
```

## 5. Architecture changes and ADRs

No Phase 1/2 decision was removed.

### ADR-007 — sandbox truthfulness and artifact gate

A subprocess cannot claim security isolation. Part 3 defines production controls and a non-production reference backend that fails closed for untrusted code or unsupported mandatory controls. Artifact bytes must pass a separate resolver and typed-ingestion binding.

### ADR-008 — immutable proposed-package envelope

The strict Phase 1/2 package remains the base report. A versioned `0.3.0` envelope adds reconciled/environment/adapter identity, resolver manifest, security, regression/target/change/rollback/policy/permission digests, and approval material. This preserves historical package validity while making Part 3 submission immutable.

### ADR-009 — reference reversible application

A generic workspace application manager makes approval/snapshot/rollback behavior testable without SAGE. It is not invoked by the default workflow and does not replace the future separate production applier process/credential boundary.

## 6. GGUF and inspection status

Implemented a bounded, header-only GGUF v2/v3 reader for:

- format version;
- tensor and metadata counts;
- typed metadata values and bounded arrays;
- architecture and identity metadata;
- declared and tensor-shape-estimated parameter count;
- declared and observed tensor quantization;
- context, embedding, block/layer, attention, feed-forward fields;
- tokenizer metadata and template metadata;
- tensor names, dimensions, type codes/names, offsets, element counts;
- duplicate names/keys, zero dimensions, and out-of-file offsets.

Unknown architectures, metadata keys, and tensor data-type codes are preserved. Architecture-specific interpretation is an optional plugin; no family branch exists.

Weights are not loaded. Big-endian and future unknown GGUF value encodings remain unsupported and fail explicitly rather than being guessed.

## 7. Sandbox status

### Production contract

Implemented:

- controlled execution specification;
- filesystem/network/permission control declarations;
- process/time/memory/file/output limits;
- mount and environment boundaries;
- requested-versus-enforced controls;
- result/stdout/stderr capture and digesting;
- declared artifact collection;
- failure isolation and cleanup reporting;
- isolation-class truthfulness.

### Available backend

`ReferenceSubprocessSandbox` is explicitly:

```text
REFERENCE_NOT_SECURITY_BOUNDARY
security_boundary_claimed = false
```

It can run only trusted engine harnesses under controls it truthfully supports. It blocks untrusted generated adapters and mandatory filesystem/network/permission isolation.

A true production container/microVM backend is not available in this environment and is not claimed.

## 8. Artifact resolver status

`SecureArtifactResolver`:

- permits only declared paths/types/sizes;
- rejects traversal, symlinks, unexpected files, undeclared candidates, root mismatch, and ID/type mismatch;
- rehashes reported and expected digests;
- validates JSON/GGUF/text types;
- copies accepted bytes into a private content-addressed store;
- reverifies content on read;
- retains run/artifact/resolver provenance.

`ProbeArtifactIngestor` refuses result artifacts not bound to the exact plan, run, probe IDs, kinds, and subjects. This prevents arbitrary artifact-to-evidence promotion.

## 9. Identity status

Identity is reconciled into separate:

- logical content model;
- artifact;
- runtime-scoped deployment;
- adapter/configuration/environment-scoped integration composition.

An atomic alias ledger detects when the same runtime alias resolves to multiple content digests. Those records are not merged. Missing artifact digest produces `PROVISIONAL_DEPLOYMENT_SCOPED` rather than tag identity.

## 10. Capability validation status

Preserved Phase 1 evidence names map as follows:

```text
METADATA_DETECTED  → DETECTED_FROM_METADATA
RUNTIME_DETECTED   → DETECTED_FROM_RUNTIME
VALIDATED_BY_PROBE → VALIDATED_BY_TEST
INFERRED           → INFERRED
UNKNOWN            → UNKNOWN
NOT_SUPPORTED      → NOT_SUPPORTED
```

Safe probes now cover:

- basic generation;
- instruction following;
- structured output;
- streaming;
- declared tool calling;
- bounded context retrieval;
- declared image input.

A pass creates `VALIDATED_BY_TEST` evidence tied to deployment/runtime, adapter, configuration, environment, and probe. Failure/error remains unknown or conflicting unless affirmative negative evidence exists. Declared maximum context remains unvalidated; the bounded probe records only its tested input size.

## 11. Adapter status

The layered adapter engine models transport, runtime protocol, deployment profile, and output normalization. Resolution order is:

1. existing exact adapter;
2. configure compatible adapter;
3. untrusted generated proposal;
4. unresolved.

Generated proposals are non-executable manifests, content-digested, `UNTRUSTED_GENERATED`, and rejected unless a production security boundary returns a passing, complete, resolver-matching result. No model-name branch exists.

## 12. Example generic proposed package

Path:

`reports/samples/part3-proposed-integration-package.json`

Canonical digest:

```text
sha256:de57f06f66f4a35ed24accf90b4fb9a682f5924b83696686c8a0f46a62b4298b
```

Summary:

```text
lifecycle_state: DRAFT_PENDING_APPROVAL
security verdict: CONDITIONAL
base evidence records: 39
base capabilities: 11
safe probe results: 6
resolver artifacts: 1
approval: pending external human decision
```

This is deterministic fixture evidence, not live model evidence. `CONDITIONAL` records the non-production test boundary; it is not a production sandbox attestation.

## 13. Approval binding status

Example request:

`reports/samples/part3-approval-request.json`

Approval scope includes exact:

- immutable package digest;
- change-set digest;
- target-snapshot digest;
- permission-set digest;
- policy digest;
- rollback-plan digest.

Example scope digest:

```text
sha256:969363383664116c31c89ae6cf6631b7ad303e335e20c3b81e32036681115562
```

Changing package bytes invalidates store verification and approval. A changed package creates a distinct scope. Only an authenticated human-authority call can create a decision.

## 14. Rollback status

Implemented and tested against temporary generic workspaces:

- snapshot of affected target files and declared configuration/registry context;
- content-addressed snapshot artifacts;
- per-file before-digest preconditions;
- atomic replace/add/remove;
- automatic rollback on post-application regression failure;
- snapshot-digest verification during restore;
- explicit `ROLLBACK_FAILED` when any restore fails.

The default workflow never calls application. No SAGE target was used.

## 15. Regression status

The framework compares before/after:

- functional checks;
- validated capability presence/score;
- compatibility rank;
- configuration digests and unexpected changes;
- new blocking risks.

Missing or failed mandatory checks produce `FAIL`; application and registry paths fail closed. Preflight is required before writes, and a failed post-check invokes rollback.

## 16. Capability registry status

Example:

`reports/samples/part3-capability-registry.example.json`

Canonical example digest:

```text
sha256:27b55c1b016dba9e6f7d6c67b779a33fcdbdd5ec4c0a13f3b375208246fa96bc
```

The registry requires:

- exact valid approval binding;
- non-blocking package security assessment;
- passing post-application regression;
- package digest match;
- `SUPPORTED`/`PARTIAL` + `VALIDATED` capability;
- `VALIDATED_BY_TEST` evidence with passing outcome.

Unvalidated claims are rejected and may only enter the separate hypothesis store. The example registry was generated in a temporary test workspace; no global registry was modified.

## 17. Example evidence chain

Path:

`reports/samples/part3-evidence-chain.example.json`

Chain:

```text
runtime/model-detail metadata declaration
→ unvalidated capability hypothesis
→ deployment-scoped passing behavioral probe
→ validated capability claim
→ adapter/configuration/environment-scoped composition identity derivation
```

Every node retains source URI/digest/locator, collector/version, subject, level, and parent evidence where derived.

## 18. Live Ollama/model validation status

Current environment:

```text
ollama executable: unavailable
local Ollama endpoint: unavailable
```

No live results were fabricated.

A generic command now exists:

```bash
python -m model_integration_engine.live_validation \
  --endpoint http://host:11434 \
  --model <exact-runtime-reference> \
  --output live-evidence.json
```

It collects actual read-only discovery and `/api/show` evidence. It intentionally reports behavioral probes blocked until a real production sandbox backend is configured. The future `qwen3:4b` run is a command argument/test deployment only; production source contains no Qwen logic.

## 19. Remaining limitations

- No true production container/microVM sandbox backend is available here.
- Live behavioral probes remain blocked without that backend and an artifact-backed probe worker.
- The reference subprocess backend is lifecycle demonstration only.
- GGUF big-endian/future unknown value encodings are not parsed.
- Direct model-directory/SafeTensors inspection remains future plugin work.
- Architecture-specific GGUF enrichment has an extension point but no unnecessary family plugins.
- Tokenizer inspection is metadata-level; full encode/decode vector validation is future work.
- Template inspection is static; render/parser compatibility needs a production sandbox worker.
- The stdlib live NDJSON transport validates chunk semantics but buffers in a worker thread.
- Application manager is an in-process reference; production still needs a separate least-privilege applier service.
- Registry persistence is atomic but does not yet include multi-process locking/signatures.
- No SAGE target profile, source, credentials, files, or registry were accessed.

## 20. Stop boundary

Part 3 stops after immutable submission and creation of a pending human approval request. No application, integration, global registration, or SAGE modification occurred. Phase 4 was not started.
