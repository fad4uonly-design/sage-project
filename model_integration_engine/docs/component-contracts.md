# Component Contracts

The JSON Schemas are the normative interchange contracts. The Python protocols in `src/model_integration_engine/contracts.py` are a dependency-light reference for implementation. A plugin can be written in another language if it communicates through a future versioned RPC boundary and preserves these semantics.

## 1. Contract-wide rules

Every operation receives an `OperationContext` containing run/correlation identity, deadline, policy snapshot, workspace scope, and cancellation signal. Every operation must:

- be deterministic for the same immutable inputs where the underlying source is unchanged;
- declare possible side effects and required permissions;
- emit observations/evidence rather than untraceable log-only conclusions;
- honor cancellation, time, byte, count, and output limits;
- return typed partial results on recoverable failure;
- never include credentials in results, logs, evidence, or packages;
- preserve unknown fields when safely possible;
- bind results to collector/plugin version and input digest;
- avoid network access unless the context grants a specific endpoint.

## 2. Common plugin descriptor

All plugins publish:

```text
plugin_id              stable reverse-DNS or package identifier
plugin_version         semantic version
contract_version       supported MIE contract version range
operations             discovery/inspection/adapter/evaluation/etc.
supported_subjects     resource kinds, formats, protocols, media types
required_permissions   filesystem/network/process/resource needs
trust_tier              trusted core / reviewed plugin / untrusted generated
priority                tie-breaker only after exact capability matching
```

Selection is by operation + subject characteristics + policy. Model name/family may appear as a finding used to choose a declarative profile, but cannot be a core dispatch branch.

## 3. Discovery port

```python
class DiscoveryProvider(Protocol):
    descriptor: PluginDescriptor
    def discover(
        self,
        request: DiscoveryRequest,
        context: OperationContext,
    ) -> AsyncIterator[DiscoveryObservation]: ...
```

### Input

- approved locators (runtime endpoints and/or filesystem roots)
- allowed resource kinds
- recursive/symlink policy
- maximum depth, entries, metadata bytes, and duration
- optional exact runtime/model reference filter

### Output

Each observation contains a resource kind, provisional identity, aliases, locator, parent relationship, observed attributes, evidence, and discovery completeness.

### Invariants

- Discovery is read-only.
- Filesystem providers do not traverse outside approved canonical roots.
- Symlinks are denied unless explicitly enabled and remain within approved roots.
- Runtime providers use read-only/list/describe operations only.
- Duplicate aliases are reconciled only after identity evidence; they are not silently merged.

## 4. Inspection port

```python
class Inspector(Protocol):
    descriptor: PluginDescriptor
    def supports(self, subject: SubjectRef, media_type: str | None) -> bool: ...
    async def inspect(
        self,
        request: InspectionRequest,
        context: OperationContext,
    ) -> InspectionReport: ...
```

### Inspection levels

- `IDENTITY_ONLY`: header/manifest/runtime identity.
- `METADATA`: key/value metadata and safe text manifests.
- `STRUCTURE`: tensor/header structure without executing weights.
- `TOKENIZER`: tokenizer vocabulary metadata, special tokens, normalization config.
- `TEMPLATE`: chat/instruction templates and role support.
- `FULL_SAFE`: all safe levels under resource limits.

### Output

An `InspectionReport` contains typed findings, raw source references, warnings, unknown fields, contradictions, completeness, and evidence IDs.

### Invariants

- Model/repository code is not imported or executed.
- A parser error cannot erase prior successful findings.
- Unknown metadata is retained in a namespaced bag with type information.
- Values from filenames are `INFERRED`; values from artifact metadata are `DETECTED_FROM_METADATA`.
- Tensor count/shape inspection is not behavioral capability evidence.

## 5. Evidence store

```python
class EvidenceStore(Protocol):
    async def append(self, record: EvidenceRecord, context: OperationContext) -> str: ...
    async def get(self, evidence_id: str, context: OperationContext) -> EvidenceRecord: ...
    async def query(self, query: EvidenceQuery, context: OperationContext) -> tuple[EvidenceRecord, ...]: ...
```

### Invariants

- Append-only; corrections create superseding records.
- IDs are stable and records are content-integrity protected.
- Derivations reference parent evidence and policy/rule version.
- Access controls can protect retained prompts/outputs separately from summary evidence.
- Deletion/redaction, if legally required, leaves a tombstone and invalidates dependent validation status.

## 6. Capability detector

```python
class CapabilityDetector(Protocol):
    descriptor: PluginDescriptor
    async def detect(
        self,
        request: CapabilityDetectionRequest,
        context: OperationContext,
    ) -> CapabilityAssessment: ...
```

### Input

- exact subject identity
- relevant inspection findings and runtime observations
- evidence records
- detector policy/taxonomy version

### Output

Candidate `CapabilityClaim` objects plus proposed validation tests.

### Invariants

- Detectors do not execute inference; evaluators do.
- Inference is labeled `INFERRED` and `UNVALIDATED`.
- Missing positive evidence yields `UNKNOWN`, not `NOT_SUPPORTED`.
- Runtime and model subjects are not interchangeable.
- Contradictory evidence yields `CONFLICTING` until a policy-supported resolution exists.

## 7. Target profile and compatibility analyzer

```python
class TargetProfileProvider(Protocol):
    async def snapshot(self, target_id: str, context: OperationContext) -> TargetSystemProfile: ...

class CompatibilityAnalyzer(Protocol):
    async def assess(
        self,
        request: CompatibilityRequest,
        context: OperationContext,
    ) -> CompatibilityAssessment: ...
```

### Target profile contents

- normalized operations and request/response schema versions
- mandatory/optional capabilities
- protocol and transport restrictions
- modality/role/template rules
- context and token-budget rules
- streaming, cancellation, timeout, and error contracts
- tool-call and structured-output semantics
- locality/privacy/resource policies
- regression suite reference

### Invariants

- A snapshot is immutable and digestable.
- Any unknown mandatory requirement makes the overall result `UNKNOWN` or `INCOMPATIBLE`, according to explicit policy—not `COMPATIBLE`.
- `COMPATIBLE_WITH_ADAPTER` identifies every adapter obligation.
- Assessment binds to exact target, deployment, runtime, adapter candidate, and policy digests.

## 8. Adapter catalog, planner, and builder

```python
class AdapterCatalog(Protocol):
    async def find_compatible(self, request: AdapterSearchRequest, context: OperationContext) -> tuple[AdapterCandidate, ...]: ...

class AdapterPlanner(Protocol):
    async def plan(self, request: AdapterPlanRequest, context: OperationContext) -> AdapterPlan: ...

class AdapterBuilder(Protocol):
    async def build_candidate(self, plan: AdapterPlan, context: OperationContext) -> AdapterCandidate: ...
```

### Resolution result

- `REUSE`: existing adapter, unchanged.
- `CONFIGURE`: existing adapter + generated/reviewed configuration.
- `COMPOSE`: existing narrow components.
- `GENERATE`: new untrusted code is unavoidable.
- `UNRESOLVED`: cannot safely bridge current requirements.

### Invariants

- The planner proves why earlier reuse levels failed before generation.
- Generated source is content-addressed, reviewable, and minimal.
- Builder output has no trust elevation.
- No adapter receives SAGE credentials or write access during candidate validation.
- The builder does not apply its output.

## 9. Normalized runtime adapter

```python
class RuntimeAdapter(Protocol):
    descriptor: PluginDescriptor
    async def describe(self, deployment: SubjectRef, context: OperationContext) -> RuntimeDescription: ...
    async def infer(self, request: InferenceRequest, context: OperationContext) -> InferenceResponse: ...
    def stream(self, request: InferenceRequest, context: OperationContext) -> AsyncIterator[InferenceEvent]: ...
    async def cancel(self, operation_id: str, context: OperationContext) -> None: ...
```

### Normalized request

- exact deployment ID
- ordered messages with role and typed parts (`text`, `image_ref`, `audio_ref`, future parts)
- optional raw prompt only when target policy allows it
- system instruction
- tool definitions using JSON Schema
- response schema/format request
- generation controls and seed where supported
- thinking preference as a request, never an assumption
- timeout, maximum output, trace level, and retention policy

### Normalized response/events

- typed output parts
- separate tool-call objects
- optional reasoning/thinking channel, subject to retention policy
- usage/timing with units and source
- finish reason mapped to normalized enum while preserving raw value
- warnings and degradation flags
- adapter/runtime/model/deployment identities
- raw response reference or digest, not necessarily embedded

### Invariants

- Unsupported request fields fail explicitly or are marked degraded; they are never silently dropped.
- A runtime-generated template and a client-generated template cannot both be applied.
- Stream assembly must be equivalent to non-streaming semantics for supported fields.
- Tool execution is outside the model adapter; validation uses fake/non-consequential tools.
- Adapter exceptions map to structured failures without losing raw status/code evidence.

## 10. Sandbox port

```python
class SandboxBackend(Protocol):
    descriptor: PluginDescriptor
    async def capabilities(self, context: OperationContext) -> SandboxCapabilities: ...
    async def execute(self, job: SandboxJob, context: OperationContext) -> SandboxResult: ...
```

### Job

- candidate source/config and digests
- immutable test bundle
- command/entry point from reviewed test harness
- read-only input mounts
- ephemeral writable path
- explicit runtime endpoint allowlist
- required controls and limits
- expected output artifacts

### Result

- outcome and structured failure
- actual enforced controls (not requested controls only)
- exit/signal/timeout data
- stdout/stderr references with truncation/redaction metadata
- produced artifact digests
- resource usage
- host-write and cleanup checks
- attestation/backend identity

A job fails policy if a mandatory control was not enforced, even if tests happened to pass.

## 11. Evaluation and regression ports

```python
class Evaluator(Protocol):
    async def evaluate(self, request: EvaluationRequest, context: OperationContext) -> EvaluationRun: ...

class RegressionRunner(Protocol):
    async def run(self, request: RegressionRequest, context: OperationContext) -> RegressionRun: ...
```

### Invariants

- Test definitions are versioned and content-addressed.
- Behavioral scores include trial count and uncertainty/reliability data where applicable.
- Environment-sensitive metrics include hardware/runtime settings.
- Test fixtures cannot call consequential tools.
- A test timeout is not a capability-negative result unless the policy explicitly defines and repeats that condition.
- Regression compares exact baseline/candidate digests and identifies affected tests.

## 12. Package builder

```python
class IntegrationPackageBuilder(Protocol):
    async def build(self, request: PackageBuildRequest, context: OperationContext) -> PackageArtifact: ...
```

### Invariants

- Validates against the normative JSON Schema.
- Resolves every evidence reference.
- Rejects secrets, host-specific credentials, and dangling artifacts.
- Includes all contradictions, risks, assumptions, and unverified requirements.
- Canonically serializes and hashes the package.
- Cannot mark approval or registration complete.

## 13. Approval gate

```python
class ApprovalGate(Protocol):
    async def request(self, request: ApprovalRequest, context: OperationContext) -> ApprovalChallenge: ...
    async def verify(self, event: ApprovalEvent, context: OperationContext) -> ApprovalDecision: ...
```

Approval scope tuple:

```text
(package_digest,
 proposed_change_set_digest,
 target_profile_digest,
 permission_set_digest,
 policy_version,
 expiry/conditions)
```

Only an authenticated human-authority event can produce `APPROVED`. Model output, generated code, test success, and the engine itself cannot.

## 14. Capability registry

```python
class CapabilityRegistry(Protocol):
    async def snapshot(self, context: OperationContext) -> RegistrySnapshot: ...
    async def register_validated(self, request: RegistrationRequest, context: OperationContext) -> RegistrySnapshot: ...
    async def disable(self, request: DisableRegistrationRequest, context: OperationContext) -> RegistrySnapshot: ...
```

### Invariants

- Registration requires approved package, successful post-application regression, and validated capability evidence.
- Update is atomic and versioned.
- Historical entries are disabled/revoked, not erased.
- Registry carries no model secrets or raw prompts.
- This port has no active implementation/wiring in Phase 1.

## 15. Future application boundary (deliberately absent)

A future `IntegrationApplier` would accept only an approved scope and perform staged, transactional, reversible changes. It must be a separate process/credential boundary. No such protocol is defined in Phase 1 source so architecture work cannot accidentally become a target write path.
