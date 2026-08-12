"""Reference ports for a generic Model Integration Engine.

These interfaces define trust and dependency boundaries; they are not concrete
implementations. In particular, there is no target-system integration applier.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from .domain import (
    AdapterCandidate,
    AdapterDisposition,
    CapabilityClaim,
    CompatibilityAssessment,
    DiscoveryObservation,
    EvidenceRecord,
    InspectionReport,
    JSONValue,
    PluginDescriptor,
    ProblemDetails,
    SubjectRef,
    TestCaseResult,
)


@runtime_checkable
class CancellationSignal(Protocol):
    @property
    def cancelled(self) -> bool: ...

    async def wait(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    timeout_seconds: float
    max_entries: int = 10_000
    max_metadata_bytes: int = 64 * 1024 * 1024
    max_output_bytes: int = 16 * 1024 * 1024
    max_processes: int = 32
    max_memory_bytes: int | None = None
    max_disk_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class OperationContext:
    run_id: str
    correlation_id: str
    deadline: datetime
    policy_id: str
    policy_version: str
    workspace_id: str
    allowed_permissions: tuple[str, ...]
    limits: ResourceLimits
    cancellation: CancellationSignal


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    locators: tuple[str, ...]
    resource_kinds: tuple[str, ...]
    recursive: bool = False
    follow_symlinks: bool = False
    max_depth: int = 1
    exact_reference: str | None = None


@dataclass(frozen=True, slots=True)
class InspectionRequest:
    subject: SubjectRef
    source_locator: str
    media_type: str | None
    levels: tuple[str, ...]
    source_digest: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceQuery:
    subjects: tuple[SubjectRef, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    observation_keys: tuple[str, ...] = ()
    levels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CapabilityDetectionRequest:
    subject: SubjectRef
    inspection_reports: tuple[InspectionReport, ...]
    evidence: tuple[EvidenceRecord, ...]
    taxonomy_version: str


@dataclass(frozen=True, slots=True)
class CapabilityAssessment:
    subject: SubjectRef
    claims: tuple[CapabilityClaim, ...]
    proposed_test_ids: tuple[str, ...]
    contradictions: tuple[str, ...]
    problem: ProblemDetails | None = None


@dataclass(frozen=True, slots=True)
class TargetRequirement:
    requirement_id: str
    description: str
    mandatory: bool
    capability_key: str | None
    parameters: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TargetSystemProfile:
    target: SubjectRef
    profile_version: str
    profile_digest: str
    normalized_contract_version: str
    requirements: tuple[TargetRequirement, ...]
    constraints: Mapping[str, JSONValue]
    regression_suite_ref: str
    capability_snapshot_digest: str


@dataclass(frozen=True, slots=True)
class CompatibilityRequest:
    deployment: SubjectRef
    runtime: SubjectRef
    target_profile: TargetSystemProfile
    claims: tuple[CapabilityClaim, ...]
    adapter_candidate: AdapterCandidate | None = None


@dataclass(frozen=True, slots=True)
class AdapterSearchRequest:
    runtime: SubjectRef
    deployment: SubjectRef
    normalized_contract_version: str
    required_operations: tuple[str, ...]
    requirement_parameters: Mapping[str, JSONValue]


@dataclass(frozen=True, slots=True)
class AdapterPlanRequest:
    search: AdapterSearchRequest
    compatibility: CompatibilityAssessment
    existing_candidates: tuple[AdapterCandidate, ...]


@dataclass(frozen=True, slots=True)
class AdapterPlan:
    plan_id: str
    disposition: AdapterDisposition
    selected_candidate: AdapterCandidate | None
    considered_adapter_ids: tuple[str, ...]
    unresolved_gaps: tuple[str, ...]
    generation_boundaries: tuple[str, ...]
    required_test_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MessagePart:
    kind: str
    value: JSONValue
    media_type: str | None = None


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    parts: tuple[MessagePart, ...]
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, JSONValue]


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    operation_id: str
    deployment: SubjectRef
    messages: tuple[Message, ...]
    system_instruction: str | None = None
    tools: tuple[ToolDefinition, ...] = ()
    response_schema: Mapping[str, JSONValue] | None = None
    generation: Mapping[str, JSONValue] = field(default_factory=dict)
    thinking_preference: str | bool | None = None
    maximum_output_tokens: int | None = None
    retain_raw_output: bool = False


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_duration_ns: int | None = None
    load_duration_ns: int | None = None
    source: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str | None
    name: str
    arguments: Mapping[str, JSONValue]


@dataclass(frozen=True, slots=True)
class InferenceResponse:
    operation_id: str
    deployment: SubjectRef
    output_parts: tuple[MessagePart, ...]
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None
    usage: Usage
    warnings: tuple[str, ...]
    degraded_fields: tuple[str, ...]
    raw_response_digest: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InferenceEvent:
    operation_id: str
    sequence: int
    event_type: str
    data: JSONValue
    terminal: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeDescription:
    runtime: SubjectRef
    deployment: SubjectRef
    protocol_version: str
    operations: tuple[str, ...]
    parameters: Mapping[str, JSONValue]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SandboxCapabilities:
    backend_id: str
    backend_version: str
    enforceable_controls: tuple[str, ...]
    unsupported_controls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SandboxJob:
    job_id: str
    candidate_manifest_digest: str
    test_bundle_digest: str
    entry_point: tuple[str, ...]
    read_only_inputs: Mapping[str, str]
    required_controls: tuple[str, ...]
    allowed_endpoints: tuple[str, ...]
    limits: ResourceLimits
    expected_outputs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SandboxResult:
    job_id: str
    backend_id: str
    outcome: str
    enforced_controls: tuple[str, ...]
    missing_controls: tuple[str, ...]
    exit_code: int | None
    timed_out: bool
    stdout_digest: str | None
    stderr_digest: str | None
    output_artifacts: Mapping[str, str]
    resource_usage: Mapping[str, JSONValue]
    host_write_observed: bool
    cleanup_complete: bool
    evidence_ids: tuple[str, ...]
    problem: ProblemDetails | None = None


@dataclass(frozen=True, slots=True)
class EvaluationRequest:
    evaluation_id: str
    suite_id: str
    suite_version: str
    suite_digest: str
    subject: SubjectRef
    adapter: AdapterCandidate
    sandbox_job: SandboxJob
    test_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    evaluation_id: str
    sandbox_result: SandboxResult
    results: tuple[TestCaseResult, ...]
    verdict: str
    evidence_ids: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegressionRequest:
    regression_id: str
    suite_ref: str
    baseline_digest: str
    candidate_digest: str
    affected_test_ids: tuple[str, ...]
    mandatory_test_ids: tuple[str, ...]
    environment_id: str


@dataclass(frozen=True, slots=True)
class RegressionRun:
    regression_id: str
    outcome: str
    baseline_digest: str
    candidate_digest: str
    results: tuple[TestCaseResult, ...]
    added_capabilities: tuple[str, ...]
    affected_tests: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PackageBuildRequest:
    package_id: str
    input_manifest_digest: str
    evidence_ids: tuple[str, ...]
    proposed_change_set_digest: str
    permission_set_digest: str
    target_profile_digest: str


@dataclass(frozen=True, slots=True)
class PackageArtifact:
    package_id: str
    schema_version: str
    package_digest: str
    uri: str
    validation_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    package: PackageArtifact
    proposed_change_set_digest: str
    target_profile_digest: str
    permission_set_digest: str
    rollback_plan_digest: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class ApprovalChallenge:
    challenge_id: str
    scope_digest: str
    summary_uri: str
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ApprovalEventInput:
    challenge_id: str
    actor_id: str
    decision: str
    scope_digest: str
    audit_reference: str
    conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    decision: str
    scope_digest: str
    valid: bool
    problem: ProblemDetails | None = None


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    registry_version: str
    registry_digest: str
    entry_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegistrationRequest:
    integration_package_digest: str
    approval_event_id: str
    post_application_regression_id: str
    capability_claim_ids: tuple[str, ...]
    deployment: SubjectRef
    adapter: SubjectRef


@dataclass(frozen=True, slots=True)
class DisableRegistrationRequest:
    entry_id: str
    reason: str
    approval_event_id: str


@runtime_checkable
class DiscoveryProvider(Protocol):
    descriptor: PluginDescriptor

    def discover(
        self, request: DiscoveryRequest, context: OperationContext
    ) -> AsyncIterator[DiscoveryObservation]: ...


@runtime_checkable
class Inspector(Protocol):
    descriptor: PluginDescriptor

    def supports(self, subject: SubjectRef, media_type: str | None) -> bool: ...

    async def inspect(
        self, request: InspectionRequest, context: OperationContext
    ) -> InspectionReport: ...


@runtime_checkable
class EvidenceStore(Protocol):
    async def append(self, record: EvidenceRecord, context: OperationContext) -> str: ...

    async def get(self, evidence_id: str, context: OperationContext) -> EvidenceRecord: ...

    async def query(
        self, query: EvidenceQuery, context: OperationContext
    ) -> tuple[EvidenceRecord, ...]: ...


@runtime_checkable
class CapabilityDetector(Protocol):
    descriptor: PluginDescriptor

    async def detect(
        self, request: CapabilityDetectionRequest, context: OperationContext
    ) -> CapabilityAssessment: ...


@runtime_checkable
class TargetProfileProvider(Protocol):
    async def snapshot(
        self, target_id: str, context: OperationContext
    ) -> TargetSystemProfile: ...


@runtime_checkable
class CompatibilityAnalyzer(Protocol):
    async def assess(
        self, request: CompatibilityRequest, context: OperationContext
    ) -> CompatibilityAssessment: ...


@runtime_checkable
class AdapterCatalog(Protocol):
    async def find_compatible(
        self, request: AdapterSearchRequest, context: OperationContext
    ) -> tuple[AdapterCandidate, ...]: ...


@runtime_checkable
class AdapterPlanner(Protocol):
    async def plan(
        self, request: AdapterPlanRequest, context: OperationContext
    ) -> AdapterPlan: ...


@runtime_checkable
class AdapterBuilder(Protocol):
    async def build_candidate(
        self, plan: AdapterPlan, context: OperationContext
    ) -> AdapterCandidate: ...


@runtime_checkable
class RuntimeAdapter(Protocol):
    descriptor: PluginDescriptor

    async def describe(
        self, deployment: SubjectRef, context: OperationContext
    ) -> RuntimeDescription: ...

    async def infer(
        self, request: InferenceRequest, context: OperationContext
    ) -> InferenceResponse: ...

    def stream(
        self, request: InferenceRequest, context: OperationContext
    ) -> AsyncIterator[InferenceEvent]: ...

    async def cancel(self, operation_id: str, context: OperationContext) -> None: ...


@runtime_checkable
class SandboxBackend(Protocol):
    descriptor: PluginDescriptor

    async def capabilities(self, context: OperationContext) -> SandboxCapabilities: ...

    async def execute(
        self, job: SandboxJob, context: OperationContext
    ) -> SandboxResult: ...


@runtime_checkable
class Evaluator(Protocol):
    async def evaluate(
        self, request: EvaluationRequest, context: OperationContext
    ) -> EvaluationRun: ...


@runtime_checkable
class RegressionRunner(Protocol):
    async def run(
        self, request: RegressionRequest, context: OperationContext
    ) -> RegressionRun: ...


@runtime_checkable
class IntegrationPackageBuilder(Protocol):
    async def build(
        self, request: PackageBuildRequest, context: OperationContext
    ) -> PackageArtifact: ...


@runtime_checkable
class ApprovalGate(Protocol):
    async def request(
        self, request: ApprovalRequest, context: OperationContext
    ) -> ApprovalChallenge: ...

    async def verify(
        self, event: ApprovalEventInput, context: OperationContext
    ) -> ApprovalDecision: ...


@runtime_checkable
class CapabilityRegistry(Protocol):
    async def snapshot(self, context: OperationContext) -> RegistrySnapshot: ...

    async def register_validated(
        self, request: RegistrationRequest, context: OperationContext
    ) -> RegistrySnapshot: ...

    async def disable(
        self, request: DisableRegistrationRequest, context: OperationContext
    ) -> RegistrySnapshot: ...
