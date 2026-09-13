"""Typed records used by the smallest Phase 2 vertical slice."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from .domain import (
    Completeness,
    EvidenceRecord,
    InspectionReport,
    JSONValue,
    Locality,
    ProblemDetails,
    SubjectRef,
)


@dataclass(frozen=True, slots=True)
class RuntimeRecord:
    subject: SubjectRef
    kind: str
    version: str
    endpoint: str
    locality: Locality
    protocol_names: tuple[str, ...]
    response_digest: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiscoveredModelRecord:
    model_subject: SubjectRef
    deployment_subject: SubjectRef
    artifact_subject: SubjectRef | None
    runtime_subject: SubjectRef
    runtime_reference: str
    aliases: tuple[str, ...]
    content_digest: str | None
    artifact_format: str | None
    size_bytes: int | None
    parameter_size_label: str | None
    quantization_label: str | None
    family_labels: tuple[str, ...]
    modified_at: str | None
    identity_status: str
    raw_summary: Mapping[str, JSONValue]
    source_digest: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    runtime: RuntimeRecord | None
    models: tuple[DiscoveredModelRecord, ...]
    evidence: tuple[EvidenceRecord, ...]
    completeness: Completeness
    observed_at: datetime
    problem: ProblemDetails | None = None


@dataclass(frozen=True, slots=True)
class ModelDetails:
    subject: SubjectRef
    deployment: SubjectRef
    artifact: SubjectRef | None
    template: str | None
    template_digest: str | None
    declared_capabilities: tuple[str, ...]
    details: Mapping[str, JSONValue]
    model_info: Mapping[str, JSONValue]
    parameters_text: str | None
    license_text: str | None
    architecture: str | None
    context_length: int | None
    tokenizer_model: str | None
    parameter_count_estimate: int | None
    unknowns: tuple[str, ...]
    raw_response_digest: str


@dataclass(frozen=True, slots=True)
class ModelInspectionResult:
    details: ModelDetails | None
    report: InspectionReport | None
    evidence: tuple[EvidenceRecord, ...]
    completeness: Completeness
    raw_response: Mapping[str, JSONValue] | None
    problem: ProblemDetails | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentInfo:
    environment_id: str
    python_version: str
    platform: str
    machine: str
    runtime_endpoint_locality: str
    sandbox_backend_id: str | None = None
    attributes: Mapping[str, JSONValue] = field(default_factory=dict)
