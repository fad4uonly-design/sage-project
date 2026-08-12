# Phase 2 Verification Report

**Date:** 2026-08-10
**Scope:** smallest read-only Ollama vertical slice
**Result:** implementation complete against deterministic fixtures; live Qwen validation unavailable

## 1. Implemented workflow

```text
Ollama discovery
→ POST /api/show inspection
→ provenance-preserving evidence
→ generic capability hypotheses
→ generic Ollama normalized adapter
→ safe probes through an isolation boundary
→ generic target compatibility assessment
→ schema-valid DRAFT package
→ STOP
```

Terminal machine state:

```text
VerticalSliceResult.state = DRAFT_PENDING_APPROVAL
package.package_state = DRAFT
package.approval.state = NOT_REQUESTED
```

No approval was requested or assumed.

## 2. What was built and why

### Ollama client and discovery

- Injectable JSON/NDJSON transport for offline tests and opt-in live access.
- Read-only calls to version, tags, show, and chat endpoints.
- Deterministic normalized runtime, model, deployment, and artifact records.
- Content digest is used when valid; missing digest creates a provisional identity rather than tag-only identity.
- Raw response digests, source URI/locator, collector version, and unknown extension fields are preserved.
- Missing/malformed runtime responses become structured recoverable/non-recoverable problems.

### Model-detail inspection

- Generic parsing of `details`, `model_info`, template, declared capabilities, parameters, and license digests.
- Architecture/context/tokenizer values are observed only when present.
- Parameter-count parsing is a labeled derivation with parent evidence.
- Missing values remain unknown.
- No model repository code is loaded.

### Evidence and capabilities

- Deterministic evidence IDs and canonical source digests.
- Capability declarations remain unvalidated until probes pass.
- API/adapter affordances create hypotheses, not behavioral validation.
- Failed/ambiguous probes result in `UNKNOWN` or `CONFLICTING`, never automatic `NOT_SUPPORTED`.
- Behavioral claims are deployment-scoped and include adapter, configuration, environment, and probe identity.

### Generic adapter

- Maps normalized messages, tools, response schema, generation settings, and thinking preference to Ollama chat requests.
- Normalizes text, thinking, tool calls, usage, finish reason, raw digest, and stream events.
- Contains no model-family/name branches.

### Probe framework

Safe probes cover:

- basic text generation;
- exact instruction following;
- structured JSON/schema outcome;
- streamed protocol assembly/terminal event;
- fake, side-effect-free tool calling when declared.

Each probe is isolated from batch failure, produces evidence, and cannot promote a claim unless the execution backend attests all mandatory isolation controls.

### Compatibility and package

- Evaluates model + runtime + adapter + target requirements.
- Internal outcomes map to compatible, incompatible, compatible-with-adapter (external label `CONDITIONALLY_COMPATIBLE`), or unknown.
- The package contains model/artifact/runtime/environment/adapter/configuration, evidence, capabilities, probes, compatibility, risks, permissions, proposed reversible change data, rollback, assumptions, and limitations.
- Package construction performs Draft 2020-12 schema validation before returning.

## 3. Automated verification

Command:

```bash
python3 -m pytest -q
```

Result:

```text
48 passed, 1 skipped in 3.40s
```

The skip is the explicitly opt-in live Ollama test:

```text
opt-in live Ollama endpoint/model not configured
```

Phase 1 baseline tests remain included and green. Phase 2 adds 24 focused offline tests plus one opt-in live test.

Compilation:

```text
python3 -m compileall -q src tests
compileall: PASS
```

Sample validation:

```text
sample draft schema validation: PASS
package_state: DRAFT
approval.state: NOT_REQUESTED
lifecycle_state: DRAFT_PENDING_APPROVAL
```

Artifact integrity:

```text
reports/phase-2-artifact-manifest.sha256: 62 files, verification PASS
```

Production-source boundary scans found:

- no `qwen` string/branch under `src/`;
- no `if model == ...` family dispatch;
- no SAGE import;
- no integration applier.

## 4. Tests added

- `test_phase2_discovery.py`
  - deterministic normalization
  - missing runtime
  - empty model list
  - malformed version/list
  - provisional identity without digest
- `test_phase2_inspection.py`
  - model detail parsing
  - observed versus derived evidence
  - missing metadata/unknown semantics
  - source provenance
- `test_phase2_capabilities.py`
  - generic hypotheses
  - declaration versus validation
  - `UNKNOWN != NOT_SUPPORTED`
- `test_phase2_adapter.py`
  - normalized request mapping
  - stream normalization
  - malformed response handling
- `test_phase2_probes.py`
  - per-probe failure isolation/evidence
  - mandatory sandbox-control blocker
- `test_phase2_compatibility.py`
  - unknown mandatory blocker
  - affirmative negative incompatibility
  - conditional compatibility through adapter
- `test_phase2_vertical_slice.py`
  - end-to-end fixture slice
  - package schema and approval stop
  - evidence/capability/compatibility examples
  - empty model-list stop
  - Qwen fixture through unchanged generic path
- `tests/live/test_ollama_live.py`
  - opt-in, read-only discovery/inspection only

## 5. Sample draft package

Path:

`reports/samples/phase2-draft-integration-package.json`

Generated package identity:

```text
integration-package-draft:fbbc10004af1f4960c3d471fb3d866d3
```

Fixture-generation digest reported by the builder:

```text
sha256:a00e1108dfd7cadf72d8e58c95cb88604ee36ddd88dcd681d97eb23ff955c48d
```

The sample has:

- 38 evidence records
- 10 capability claims
- 5 safe probe results
- `COMPATIBLE_WITH_ADAPTER` against the synthetic target
- a blocking `risk-fixture-only` risk
- no approval, application, regression pass, or registry update

## 6. Evidence example

```json
{
  "evidence_id": "evidence:3a4e0300697d0eac32edb11025b9b1a5",
  "observation_key": "probe.basic_generation",
  "level": "VALIDATED_BY_TEST",
  "outcome": "PASS",
  "subject": {"kind": "DEPLOYMENT"},
  "environment_id": "env:deterministic-fixture",
  "source": {
    "uri": "sandbox://deterministic-fixture-sandbox/fixture-sandbox-run/probe:1e83815becfaacbf47fd72682fd6ae08"
  }
}
```

This is fixture evidence and is not represented as live deployment evidence.

## 7. Capability examples

```text
generation.text     SUPPORTED  VALIDATED    DETECTED_FROM_METADATA + VALIDATED_BY_TEST
reasoning.general   UNKNOWN    UNVALIDATED  INFERRED
context.long        SUPPORTED  UNVALIDATED  DETECTED_FROM_METADATA
```

The context claim means only that long-context metadata was observed. It does not claim validated usable context.

## 8. Compatibility example

```text
status: COMPATIBLE_WITH_ADAPTER
external label: CONDITIONALLY_COMPATIBLE
mandatory blockers: none
mandatory unknowns: none
```

This result applies only to the deterministic fixture composition. The blocking fixture-only risk prevents using it as live integration evidence.

## 9. Files created

Production:

- `src/model_integration_engine/evidence.py`
- `src/model_integration_engine/phase2_models.py`
- `src/model_integration_engine/plugins/ollama/client.py`
- `src/model_integration_engine/plugins/ollama/discovery.py`
- `src/model_integration_engine/plugins/ollama/inspection.py`
- `src/model_integration_engine/plugins/ollama/adapter.py`
- `src/model_integration_engine/capabilities/hypotheses.py`
- `src/model_integration_engine/application/probes.py`
- `src/model_integration_engine/application/vertical_slice.py`
- `src/model_integration_engine/compatibility/evaluator.py`
- `src/model_integration_engine/packaging/draft.py`
- package `__init__.py` files

Tests/fixtures:

- `tests/phase2_support.py`
- seven focused `test_phase2_*.py` files
- `tests/live/test_ollama_live.py`
- neutral and Qwen JSON fixtures under `tests/fixtures/ollama/`

Documentation/output:

- `docs/decisions/ADR-006-typed-probe-execution-boundary.md`
- `reports/samples/phase2-draft-integration-package.json`
- this report

Files changed:

- `README.md`
- `pyproject.toml`
- `src/model_integration_engine/__init__.py`

Phase 1 architecture/schema/domain/contracts remain in place; existing tests were preserved.

## 10. Architecture decision required

ADR-006 records one concrete implementation gap: the Phase 1 `SandboxBackend` returns artifact digests but Phase 1 did not define the artifact resolver needed for typed probe-result ingestion. Phase 2 therefore adds a narrow application-level `ProbeExecutionBackend` specialization. It does not weaken or replace the Phase 1 sandbox boundary.

No other Phase 1 redesign was required.

## 11. Known limitations and unverified assumptions

- This environment has no Ollama executable and no server at `127.0.0.1:11434`.
- Live `qwen3:4b` validation was not run and was not faked.
- The supplied “Qwen3 4B Thinking 2507” identity is still unreconciled with a local content digest.
- The deterministic probe backend is a test double, not a security sandbox. It creates a blocking package risk.
- A production `SandboxBackend` + artifact-resolver adapter remains to be implemented before live behavioral probes.
- The stdlib NDJSON transport buffers events in a worker thread; it validates chunk semantics but not low-latency delivery.
- Direct GGUF header/tensor inspection is not part of this smallest slice; artifact identity is runtime-reported.
- Probe thresholds are intentionally minimal and establish narrow contract behavior, not broad quality.
- Preflight/post-application regression, approval, target application, rollback execution, and registry update remain unperformed.
- The sample target is synthetic and no SAGE interface was accessed.

## 12. Stop boundary

Phase 2 performed no SAGE modification, host application modification, plugin installation, generated-code host execution, active registration, application, or approval request. Do not proceed to Phase 3 from this report.
