"""Generic Ollama model-detail inspection using POST /api/show."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass, field
from typing import Any

from ...contracts import InspectionRequest, OperationContext
from ...domain import (
    Completeness,
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    InspectionFinding,
    InspectionReport,
    JSONValue,
    PluginDescriptor,
    ProblemDetails,
    TrustState,
    WorkflowStage,
)
from ...evidence import EvidenceFactory, deterministic_id, sha256_digest, utc_now
from ...phase2_models import (
    DiscoveredModelRecord,
    ModelDetails,
    ModelInspectionResult,
)
from .client import OllamaClient, OllamaClientError

_PARAMETER_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMBT])\s*$", re.IGNORECASE)
_PARAMETER_MULTIPLIER = {
    "K": 1_000,
    "M": 1_000_000,
    "B": 1_000_000_000,
    "T": 1_000_000_000_000,
}


def _json_value(value: Any) -> JSONValue:
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _parse_parameter_count(label: str | None) -> int | None:
    if label is None:
        return None
    match = _PARAMETER_PATTERN.match(label)
    if match is None:
        return None
    try:
        magnitude = Decimal(match.group(1))
    except InvalidOperation:
        return None
    return int(magnitude * _PARAMETER_MULTIPLIER[match.group(2).upper()])


@dataclass(slots=True)
class OllamaModelInspector:
    client: OllamaClient
    clock: callable = utc_now
    descriptor: PluginDescriptor = field(
        default_factory=lambda: PluginDescriptor(
            plugin_id="mie.inspector.ollama-model-details",
            plugin_version="0.2.0",
            contract_version="0.1.0",
            operations=("inspect_model_details",),
            supported_subjects=("MODEL_DEPLOYMENT", "ARTIFACT"),
            required_permissions=("network:configured-ollama-endpoint",),
            trust_state=TrustState.TRUSTED_EXISTING,
        )
    )

    async def inspect_model(
        self,
        model: DiscoveredModelRecord,
        *,
        verbose: bool = True,
    ) -> ModelInspectionResult:
        factory = EvidenceFactory(
            self.descriptor.plugin_id,
            self.descriptor.plugin_version,
            self.clock,
        )
        try:
            raw_response = await self.client.show(model.runtime_reference, verbose=verbose)
        except OllamaClientError as exc:
            return ModelInspectionResult(
                details=None,
                report=None,
                evidence=(),
                completeness=Completeness.FAILED,
                raw_response=None,
                problem=ProblemDetails(
                    code=exc.code,
                    stage=WorkflowStage.INSPECTED,
                    message=str(exc),
                    retryable=exc.retryable,
                    subject=model.deployment_subject,
                    remediation=("Retry read-only model-detail inspection.",),
                    details={"status_code": exc.status_code},
                ),
            )

        normalized_response = _json_value(dict(raw_response))
        assert isinstance(normalized_response, dict)
        response_digest = sha256_digest(normalized_response)
        source_uri = f"{self.client.endpoint}/api/show"
        evidence = []
        findings = []

        raw_evidence = factory.create(
            kind=EvidenceKind.RUNTIME_OBSERVATION,
            level=EvidenceLevel.DETECTED_FROM_RUNTIME,
            subject=model.deployment_subject,
            observation_key="deployment.model_details_response",
            observed_value={
                "response_digest": response_digest,
                "top_level_fields": sorted(normalized_response),
            },
            source_uri=source_uri,
            source_digest=response_digest,
            locator="/",
            outcome=EvidenceOutcome.NOT_APPLICABLE,
        )
        evidence.append(raw_evidence)

        def add_fact(
            path: str,
            value: JSONValue,
            *,
            subject=model.artifact_subject or model.deployment_subject,
        ) -> str:
            item = factory.create(
                kind=EvidenceKind.METADATA_FIELD,
                level=EvidenceLevel.DETECTED_FROM_METADATA,
                subject=subject,
                observation_key=path,
                observed_value=value,
                source_uri=source_uri,
                source_digest=response_digest,
                locator="/" + path.replace(".", "/"),
                outcome=EvidenceOutcome.NOT_APPLICABLE,
            )
            evidence.append(item)
            findings.append(
                InspectionFinding(
                    path=path,
                    raw_value=value,
                    normalized_value=value,
                    value_type=type(value).__name__,
                    source=item.source,
                    evidence_level=item.level,
                    evidence_id=item.evidence_id,
                )
            )
            return item.evidence_id

        details_map = _mapping(raw_response.get("details"))
        model_info_map = _mapping(raw_response.get("model_info"))

        details_evidence: dict[str, str] = {}
        for key in sorted(details_map):
            value = _json_value(details_map[key])
            details_evidence[key] = add_fact(f"details.{key}", value)

        metadata_evidence: dict[str, str] = {}
        for key in sorted(model_info_map):
            value = _json_value(model_info_map[key])
            metadata_evidence[key] = add_fact(key, value)

        template = _text(raw_response.get("template"))
        template_digest = sha256_digest(template.encode("utf-8")) if template is not None else None
        if template is not None:
            add_fact("template", {"digest": template_digest, "length": len(template)})

        capabilities_raw = raw_response.get("capabilities")
        declared_capabilities = (
            tuple(sorted(set(item for item in capabilities_raw if isinstance(item, str))))
            if isinstance(capabilities_raw, list)
            else ()
        )
        if isinstance(capabilities_raw, list):
            add_fact("capabilities", list(declared_capabilities), subject=model.deployment_subject)

        parameters_text = _text(raw_response.get("parameters"))
        if parameters_text is not None:
            add_fact(
                "parameters",
                {"digest": sha256_digest(parameters_text.encode("utf-8")), "length": len(parameters_text)},
                subject=model.deployment_subject,
            )

        license_text = _text(raw_response.get("license"))
        if license_text is not None:
            add_fact(
                "license",
                {"digest": sha256_digest(license_text.encode("utf-8")), "length": len(license_text)},
            )

        architecture_value = model_info_map.get("general.architecture")
        architecture = architecture_value if isinstance(architecture_value, str) else None
        tokenizer_value = model_info_map.get("tokenizer.ggml.model")
        tokenizer_model = tokenizer_value if isinstance(tokenizer_value, str) else None

        context_length = None
        context_candidates = {
            key: value
            for key, value in model_info_map.items()
            if key.endswith(".context_length")
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value > 0
        }
        architecture_context_key = (
            f"{architecture}.context_length" if architecture is not None else None
        )
        if architecture_context_key and architecture_context_key in context_candidates:
            context_length = int(context_candidates[architecture_context_key])
        elif len(context_candidates) == 1:
            context_length = int(next(iter(context_candidates.values())))

        parameter_count = _parse_parameter_count(model.parameter_size_label)
        if parameter_count is not None:
            parent_ids = tuple(
                evidence_id
                for key, evidence_id in details_evidence.items()
                if key == "parameter_size"
            ) or model.evidence_ids[:1]
            derived = factory.create(
                kind=EvidenceKind.DERIVATION,
                level=EvidenceLevel.INFERRED,
                subject=model.model_subject,
                observation_key="derived.parameter_count_estimate",
                observed_value={
                    "estimate": parameter_count,
                    "source_label": model.parameter_size_label,
                },
                source_uri="urn:mie:derivation:parameter-size-label",
                source_digest=sha256_digest(
                    {"label": model.parameter_size_label, "rule": "si-size-label-v1"}
                ),
                locator="si-size-label-v1",
                outcome=EvidenceOutcome.NOT_APPLICABLE,
                derived_from=parent_ids,
            )
            evidence.append(derived)

        unknowns = []
        for name, value in (
            ("architecture", architecture),
            ("context_length", context_length),
            ("tokenizer_model", tokenizer_model),
            ("chat_template", template),
        ):
            if value is None:
                unknowns.append(name)

        completed_levels = ["IDENTITY_ONLY", "METADATA"]
        if template is not None:
            completed_levels.append("TEMPLATE")
        if tokenizer_model is not None:
            completed_levels.append("TOKENIZER")
        completeness = Completeness.COMPLETE if not unknowns else Completeness.PARTIAL
        report = InspectionReport(
            report_id=deterministic_id(
                "inspection", model.deployment_subject.subject_id, response_digest
            ),
            inspector_id=self.descriptor.plugin_id,
            inspector_version=self.descriptor.plugin_version,
            subject=model.artifact_subject or model.deployment_subject,
            requested_levels=("IDENTITY_ONLY", "METADATA", "TOKENIZER", "TEMPLATE"),
            completed_levels=tuple(completed_levels),
            findings=tuple(findings),
            unknown_fields={},
            contradictions=(),
            completeness=completeness,
            evidence_ids=tuple(item.evidence_id for item in evidence),
        )
        details = ModelDetails(
            subject=model.model_subject,
            deployment=model.deployment_subject,
            artifact=model.artifact_subject,
            template=template,
            template_digest=template_digest,
            declared_capabilities=declared_capabilities,
            details={str(key): _json_value(value) for key, value in details_map.items()},
            model_info={str(key): _json_value(value) for key, value in model_info_map.items()},
            parameters_text=parameters_text,
            license_text=license_text,
            architecture=architecture,
            context_length=context_length,
            tokenizer_model=tokenizer_model,
            parameter_count_estimate=parameter_count,
            unknowns=tuple(unknowns),
            raw_response_digest=response_digest,
        )
        return ModelInspectionResult(
            details=details,
            report=report,
            evidence=tuple(evidence),
            completeness=completeness,
            raw_response=normalized_response,
        )

    def supports(self, subject, media_type: str | None) -> bool:
        return subject.kind.value in {"DEPLOYMENT", "ARTIFACT"}

    async def inspect(
        self, request: InspectionRequest, context: OperationContext
    ) -> InspectionReport:
        raise NotImplementedError(
            "Use inspect_model with a discovered deployment record so tag aliases "
            "remain bound to runtime content identity."
        )
