"""Dependency-light reference domain values for MIE Phase 1.

Persisted integration packages and registry entries are governed by the JSON
Schemas. These values demonstrate the key semantic boundaries and invariants;
they intentionally contain no runtime, model-family, or target integration code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class SubjectKind(StrEnum):
    MODEL = "MODEL"
    ARTIFACT = "ARTIFACT"
    RUNTIME = "RUNTIME"
    DEPLOYMENT = "DEPLOYMENT"
    ADAPTER = "ADAPTER"
    TOOL = "TOOL"
    SKILL = "SKILL"
    KNOWLEDGE = "KNOWLEDGE"
    INTEGRATION = "INTEGRATION"
    TARGET = "TARGET"


class ResourceKind(StrEnum):
    RUNTIME_INSTANCE = "RUNTIME_INSTANCE"
    MODEL_DEPLOYMENT = "MODEL_DEPLOYMENT"
    ARTIFACT = "ARTIFACT"
    MODEL_DIRECTORY = "MODEL_DIRECTORY"


class ArtifactFormat(StrEnum):
    GGUF = "GGUF"
    MODEL_DIRECTORY = "MODEL_DIRECTORY"
    SAFETENSORS = "SAFETENSORS"
    ONNX = "ONNX"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class Locality(StrEnum):
    LOCAL = "LOCAL"
    LAN = "LAN"
    REMOTE = "REMOTE"
    UNKNOWN = "UNKNOWN"


class Completeness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class EvidenceLevel(StrEnum):
    DETECTED_FROM_METADATA = "DETECTED_FROM_METADATA"
    DETECTED_FROM_RUNTIME = "DETECTED_FROM_RUNTIME"
    VALIDATED_BY_TEST = "VALIDATED_BY_TEST"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class EvidenceKind(StrEnum):
    METADATA_FIELD = "METADATA_FIELD"
    RUNTIME_OBSERVATION = "RUNTIME_OBSERVATION"
    TEST_RESULT = "TEST_RESULT"
    STATIC_ANALYSIS = "STATIC_ANALYSIS"
    PROVIDER_DOCUMENT = "PROVIDER_DOCUMENT"
    USER_INPUT = "USER_INPUT"
    DERIVATION = "DERIVATION"


class EvidenceOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CapabilityClass(StrEnum):
    MODEL_CAPABILITY = "MODEL_CAPABILITY"
    RUNTIME_CAPABILITY = "RUNTIME_CAPABILITY"
    TOOL_CAPABILITY = "TOOL_CAPABILITY"
    SKILL_CAPABILITY = "SKILL_CAPABILITY"
    KNOWLEDGE_CAPABILITY = "KNOWLEDGE_CAPABILITY"
    INTEGRATION_CAPABILITY = "INTEGRATION_CAPABILITY"


class SupportState(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    UNKNOWN = "UNKNOWN"
    CONFLICTING = "CONFLICTING"


class ValidationState(StrEnum):
    UNVALIDATED = "UNVALIDATED"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class CompatibilityStatus(StrEnum):
    COMPATIBLE = "COMPATIBLE"
    COMPATIBLE_WITH_ADAPTER = "COMPATIBLE_WITH_ADAPTER"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


class RequirementStatus(StrEnum):
    SATISFIED = "SATISFIED"
    SATISFIED_WITH_ADAPTER = "SATISFIED_WITH_ADAPTER"
    UNSATISFIED = "UNSATISFIED"
    UNKNOWN = "UNKNOWN"


class AdapterOrigin(StrEnum):
    EXISTING = "EXISTING"
    CONFIGURED = "CONFIGURED"
    COMPOSED = "COMPOSED"
    GENERATED = "GENERATED"


class AdapterDisposition(StrEnum):
    REUSE = "REUSE"
    CONFIGURE = "CONFIGURE"
    COMPOSE = "COMPOSE"
    GENERATE = "GENERATE"
    UNRESOLVED = "UNRESOLVED"


class TrustState(StrEnum):
    TRUSTED_EXISTING = "TRUSTED_EXISTING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNTRUSTED_GENERATED = "UNTRUSTED_GENERATED"


class ApprovalState(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class WorkflowStage(StrEnum):
    NEW = "NEW"
    DISCOVERED = "DISCOVERED"
    INSPECTED = "INSPECTED"
    ASSESSED = "ASSESSED"
    PLANNED = "PLANNED"
    CANDIDATE_BUILT = "CANDIDATE_BUILT"
    SANDBOXED = "SANDBOXED"
    EVALUATED = "EVALUATED"
    REGRESSION_PREFLIGHTED = "REGRESSION_PREFLIGHTED"
    PROPOSED = "PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INTEGRATING = "INTEGRATING"
    INTEGRATED = "INTEGRATED"
    REGRESSION_VERIFIED = "REGRESSION_VERIFIED"
    REGISTERED = "REGISTERED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


class TestOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class RiskSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class SubjectRef:
    kind: SubjectKind
    subject_id: str
    version: str | None = None
    digest: str | None = None

    def __post_init__(self) -> None:
        if not self.subject_id.strip():
            raise ValueError("subject_id must be non-empty")


@dataclass(frozen=True, slots=True)
class SourceRef:
    uri: str
    digest: str | None = None
    locator: str | None = None

    def __post_init__(self) -> None:
        if not self.uri.strip():
            raise ValueError("source uri must be non-empty")


@dataclass(frozen=True, slots=True)
class PluginDescriptor:
    plugin_id: str
    plugin_version: str
    contract_version: str
    operations: tuple[str, ...]
    supported_subjects: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    trust_state: TrustState = TrustState.REVIEW_REQUIRED


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    kind: EvidenceKind
    level: EvidenceLevel
    subject: SubjectRef
    observation_key: str
    observed_value: JSONValue
    source: SourceRef
    collector_id: str
    collector_version: str
    collected_at: datetime
    outcome: EvidenceOutcome | None = None
    environment_id: str | None = None
    derived_from: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    redacted: bool = False

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.observation_key:
            raise ValueError("evidence_id and observation_key must be non-empty")
        if self.collected_at.tzinfo is None:
            raise ValueError("collected_at must be timezone-aware")
        if self.kind is EvidenceKind.DERIVATION and not self.derived_from:
            raise ValueError("derived evidence must reference parent evidence")
        if self.level is EvidenceLevel.VALIDATED_BY_TEST:
            if self.kind is not EvidenceKind.TEST_RESULT:
                raise ValueError("VALIDATED_BY_TEST requires TEST_RESULT evidence")
            if self.outcome is not EvidenceOutcome.PASS:
                raise ValueError("VALIDATED_BY_TEST requires a passing outcome")


@dataclass(frozen=True, slots=True)
class CapabilityClaim:
    claim_id: str
    capability_key: str
    capability_class: CapabilityClass
    subject: SubjectRef
    support: SupportState
    validation: ValidationState
    evidence_levels: tuple[EvidenceLevel, ...]
    evidence_ids: tuple[str, ...]
    parameters: Mapping[str, JSONValue] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    policy_version: str = "unassigned"
    assessed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.claim_id or not self.capability_key:
            raise ValueError("claim_id and capability_key must be non-empty")
        if self.support is not SupportState.UNKNOWN and not self.evidence_ids:
            raise ValueError("non-UNKNOWN support requires evidence")
        if self.validation is ValidationState.VALIDATED:
            if self.support not in {SupportState.SUPPORTED, SupportState.PARTIAL}:
                raise ValueError("validated claims must be supported or partial")
            if EvidenceLevel.VALIDATED_BY_TEST not in self.evidence_levels:
                raise ValueError("validated claims require VALIDATED_BY_TEST")
            if not self.evidence_ids:
                raise ValueError("validated claims require evidence IDs")
        if (
            self.support is SupportState.NOT_SUPPORTED
            and EvidenceLevel.NOT_SUPPORTED not in self.evidence_levels
        ):
            raise ValueError("NOT_SUPPORTED requires affirmative negative evidence")
        if (
            self.validation is ValidationState.VALIDATED
            and set(self.evidence_levels) == {EvidenceLevel.INFERRED}
        ):
            raise ValueError("inference alone cannot be validated")
        if self.support is SupportState.CONFLICTING and not self.contradictions:
            raise ValueError("conflicting support requires contradiction references")
        if self.assessed_at is not None and self.assessed_at.tzinfo is None:
            raise ValueError("assessed_at must be timezone-aware")

    @property
    def is_registry_eligible(self) -> bool:
        return (
            self.validation is ValidationState.VALIDATED
            and self.support in {SupportState.SUPPORTED, SupportState.PARTIAL}
            and EvidenceLevel.VALIDATED_BY_TEST in self.evidence_levels
        )


@dataclass(frozen=True, slots=True)
class DiscoveryObservation:
    observation_id: str
    resource_kind: ResourceKind
    subject: SubjectRef
    locator: str
    aliases: tuple[str, ...]
    attributes: Mapping[str, JSONValue]
    evidence_ids: tuple[str, ...]
    completeness: Completeness
    parent: SubjectRef | None = None


@dataclass(frozen=True, slots=True)
class InspectionFinding:
    path: str
    raw_value: JSONValue
    normalized_value: JSONValue
    value_type: str
    source: SourceRef
    evidence_level: EvidenceLevel
    evidence_id: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InspectionReport:
    report_id: str
    inspector_id: str
    inspector_version: str
    subject: SubjectRef
    requested_levels: tuple[str, ...]
    completed_levels: tuple[str, ...]
    findings: tuple[InspectionFinding, ...]
    unknown_fields: Mapping[str, JSONValue]
    contradictions: tuple[str, ...]
    completeness: Completeness
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RequirementAssessment:
    requirement_id: str
    description: str
    mandatory: bool
    status: RequirementStatus
    evidence_ids: tuple[str, ...]
    adapter_obligations: tuple[str, ...] = ()
    remediation: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CompatibilityAssessment:
    assessment_id: str
    subject: SubjectRef
    target: SubjectRef
    target_profile_digest: str
    status: CompatibilityStatus
    requirements: tuple[RequirementAssessment, ...]
    blockers: tuple[str, ...]
    unknowns: tuple[str, ...]
    required_permissions: tuple[str, ...]
    policy_version: str

    def __post_init__(self) -> None:
        mandatory_unknown = any(
            item.mandatory and item.status is RequirementStatus.UNKNOWN
            for item in self.requirements
        )
        if mandatory_unknown and self.status is CompatibilityStatus.COMPATIBLE:
            raise ValueError("unknown mandatory requirement cannot be compatible")
        mandatory_unsatisfied = any(
            item.mandatory and item.status is RequirementStatus.UNSATISFIED
            for item in self.requirements
        )
        if mandatory_unsatisfied and self.status in {
            CompatibilityStatus.COMPATIBLE,
            CompatibilityStatus.COMPATIBLE_WITH_ADAPTER,
        }:
            raise ValueError("unsatisfied mandatory requirement blocks compatibility")


@dataclass(frozen=True, slots=True)
class AdapterCandidate:
    adapter_id: str
    adapter_version: str
    origin: AdapterOrigin
    trust_state: TrustState
    contract_version: str
    source_manifest_digest: str | None
    configuration_digest: str | None
    supported_operations: tuple[str, ...]
    required_permissions: tuple[str, ...]
    validation: ValidationState = ValidationState.UNVALIDATED
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.origin is AdapterOrigin.GENERATED:
            if self.trust_state is not TrustState.UNTRUSTED_GENERATED:
                raise ValueError("generated adapters must begin untrusted")
            if not self.source_manifest_digest:
                raise ValueError("generated adapters require a source manifest digest")
        if self.validation is ValidationState.VALIDATED and not self.evidence_ids:
            raise ValueError("validated adapters require evidence")


@dataclass(frozen=True, slots=True)
class ProblemDetails:
    code: str
    stage: WorkflowStage
    message: str
    retryable: bool
    subject: SubjectRef | None = None
    evidence_ids: tuple[str, ...] = ()
    remediation: tuple[str, ...] = ()
    cleanup_complete: bool | None = None
    details: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TestCaseResult:
    test_id: str
    suite_id: str
    suite_version: str
    subject: SubjectRef
    environment_id: str
    fixture_digest: str
    outcome: TestOutcome
    assertions: Mapping[str, JSONValue]
    measurements: Mapping[str, JSONValue]
    evidence_ids: tuple[str, ...]
    output_digest: str | None = None
    problem: ProblemDetails | None = None


@dataclass(frozen=True, slots=True)
class ApprovalScope:
    package_digest: str
    proposed_change_set_digest: str
    target_profile_digest: str
    permission_set_digest: str
    policy_version: str
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        values = (
            self.package_digest,
            self.proposed_change_set_digest,
            self.target_profile_digest,
            self.permission_set_digest,
            self.policy_version,
        )
        if any(not value.strip() for value in values):
            raise ValueError("approval scope fields must be non-empty")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("approval expiry must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ApprovalEvent:
    event_id: str
    state: ApprovalState
    actor_id: str
    decided_at: datetime
    scope: ApprovalScope
    conditions: tuple[str, ...] = ()
    audit_reference: str | None = None

    def __post_init__(self) -> None:
        if self.decided_at.tzinfo is None:
            raise ValueError("approval time must be timezone-aware")
        if self.state is ApprovalState.APPROVED and not self.audit_reference:
            raise ValueError("approved event requires an audit reference")


def canonical_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a recursively key-sorted JSON-like mapping for hashing layers.

    This helper does not serialize floats or timestamps and therefore is not the
    package canonicalization policy. It exists only as a safe reference utility.
    """

    def normalize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {key: normalize(item[key]) for key in sorted(item)}
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        return item

    return normalize(value)
