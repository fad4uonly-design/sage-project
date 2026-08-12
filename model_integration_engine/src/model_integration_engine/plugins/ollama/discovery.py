"""Generic read-only Ollama discovery provider."""

from __future__ import annotations

import ipaddress
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from ...contracts import DiscoveryRequest, OperationContext
from ...domain import (
    Completeness,
    DiscoveryObservation,
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    JSONValue,
    Locality,
    PluginDescriptor,
    ProblemDetails,
    ResourceKind,
    SubjectKind,
    SubjectRef,
    TrustState,
    WorkflowStage,
)
from ...evidence import EvidenceFactory, deterministic_id, sha256_digest, utc_now
from ...phase2_models import DiscoveryResult, DiscoveredModelRecord, RuntimeRecord
from .client import OllamaClient, OllamaClientError, OllamaProtocolError


def _normalize_json(value: Any) -> JSONValue:
    if isinstance(value, dict):
        return {str(key): _normalize_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _digest_from_ollama(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if candidate.startswith("sha256:"):
        candidate = candidate.removeprefix("sha256:")
    if len(candidate) == 64 and all(char in "0123456789abcdef" for char in candidate):
        return "sha256:" + candidate
    return None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _locality(endpoint: str) -> Locality:
    hostname = (urlparse(endpoint).hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return Locality.LOCAL
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return Locality.REMOTE if hostname else Locality.UNKNOWN
    if address.is_loopback:
        return Locality.LOCAL
    if address.is_private or address.is_link_local:
        return Locality.LAN
    return Locality.REMOTE


@dataclass(slots=True)
class OllamaDiscoveryProvider:
    client: OllamaClient
    clock: callable = utc_now
    descriptor: PluginDescriptor = field(
        default_factory=lambda: PluginDescriptor(
            plugin_id="mie.discovery.ollama-api",
            plugin_version="0.2.0",
            contract_version="0.1.0",
            operations=("discover_runtime", "list_models"),
            supported_subjects=("RUNTIME_INSTANCE", "MODEL_DEPLOYMENT"),
            required_permissions=("network:configured-ollama-endpoint",),
            trust_state=TrustState.TRUSTED_EXISTING,
        )
    )

    async def discover_all(self) -> DiscoveryResult:
        observed_at: datetime = self.clock()
        factory = EvidenceFactory(
            self.descriptor.plugin_id,
            self.descriptor.plugin_version,
            self.clock,
        )
        runtime: RuntimeRecord | None = None
        evidence = []

        try:
            version_response = self.client.version()
            tags_response = None
            version_raw = await version_response
        except OllamaClientError as exc:
            return DiscoveryResult(
                runtime=None,
                models=(),
                evidence=(),
                completeness=Completeness.FAILED,
                observed_at=observed_at,
                problem=_problem(exc, WorkflowStage.NEW),
            )

        version = str(version_raw["version"])
        version_digest = sha256_digest(version_raw)
        runtime_id = deterministic_id("runtime:ollama", self.client.endpoint)
        runtime_digest = sha256_digest(
            {"kind": "ollama", "endpoint": self.client.endpoint, "version": version}
        )
        runtime_subject = SubjectRef(
            SubjectKind.RUNTIME,
            runtime_id,
            version=version,
            digest=runtime_digest,
        )
        version_evidence = factory.create(
            kind=EvidenceKind.RUNTIME_OBSERVATION,
            level=EvidenceLevel.DETECTED_FROM_RUNTIME,
            subject=runtime_subject,
            observation_key="runtime.version",
            observed_value=version,
            source_uri=f"{self.client.endpoint}/api/version",
            source_digest=version_digest,
            locator="/version",
            outcome=EvidenceOutcome.NOT_APPLICABLE,
        )
        evidence.append(version_evidence)
        runtime = RuntimeRecord(
            subject=runtime_subject,
            kind="ollama",
            version=version,
            endpoint=self.client.endpoint,
            locality=_locality(self.client.endpoint),
            protocol_names=("ollama-native-http",),
            response_digest=version_digest,
            evidence_ids=(version_evidence.evidence_id,),
        )

        try:
            tags_response = await self.client.tags()
        except OllamaClientError as exc:
            return DiscoveryResult(
                runtime=runtime,
                models=(),
                evidence=tuple(evidence),
                completeness=Completeness.PARTIAL,
                observed_at=observed_at,
                problem=_problem(exc, WorkflowStage.DISCOVERED),
            )

        tags_digest = sha256_digest(tags_response)
        models_value = tags_response["models"]
        assert isinstance(models_value, list)  # client contract
        list_evidence = factory.create(
            kind=EvidenceKind.RUNTIME_OBSERVATION,
            level=EvidenceLevel.DETECTED_FROM_RUNTIME,
            subject=runtime_subject,
            observation_key="runtime.model_list",
            observed_value={"count": len(models_value)},
            source_uri=f"{self.client.endpoint}/api/tags",
            source_digest=tags_digest,
            locator="/models",
            outcome=EvidenceOutcome.NOT_APPLICABLE,
        )
        evidence.append(list_evidence)

        normalized_models: list[DiscoveredModelRecord] = []
        try:
            for index, raw_item in enumerate(models_value):
                assert isinstance(raw_item, Mapping)
                model, model_evidence = self._normalize_model(
                    raw_item,
                    index=index,
                    tags_digest=tags_digest,
                    runtime=runtime,
                    factory=factory,
                )
                normalized_models.append(model)
                evidence.extend(model_evidence)
        except OllamaProtocolError as exc:
            return DiscoveryResult(
                runtime=runtime,
                models=tuple(normalized_models),
                evidence=tuple(evidence),
                completeness=Completeness.PARTIAL,
                observed_at=observed_at,
                problem=_problem(exc, WorkflowStage.DISCOVERED),
            )

        normalized_models.sort(
            key=lambda item: (item.runtime_reference, item.content_digest or "")
        )
        return DiscoveryResult(
            runtime=runtime,
            models=tuple(normalized_models),
            evidence=tuple(evidence),
            completeness=Completeness.COMPLETE,
            observed_at=observed_at,
        )

    def _normalize_model(
        self,
        raw: Mapping[str, object],
        *,
        index: int,
        tags_digest: str,
        runtime: RuntimeRecord,
        factory: EvidenceFactory,
    ) -> tuple[DiscoveredModelRecord, tuple]:
        name = _optional_string(raw.get("name"))
        model_alias = _optional_string(raw.get("model"))
        runtime_reference = model_alias or name
        if not runtime_reference:
            raise OllamaProtocolError(
                "MALFORMED_MODEL_SUMMARY",
                f"Model summary at index {index} has no usable name/model reference",
                retryable=False,
            )

        content_digest = _digest_from_ollama(raw.get("digest"))
        normalized_raw = _normalize_json(dict(raw))
        summary_digest = sha256_digest(normalized_raw)
        identity_material = content_digest or sha256_digest(
            {
                "runtime": runtime.subject.subject_id,
                "summary_digest": summary_digest,
                "reference": runtime_reference,
            }
        )
        model_subject = SubjectRef(
            SubjectKind.MODEL,
            deterministic_id("model:ollama", identity_material),
            digest=content_digest,
        )
        deployment_subject = SubjectRef(
            SubjectKind.DEPLOYMENT,
            deterministic_id(
                "deployment:ollama",
                runtime.subject.subject_id,
                runtime_reference,
                identity_material,
            ),
            digest=sha256_digest(
                {
                    "runtime": runtime.subject.digest,
                    "reference": runtime_reference,
                    "content": content_digest,
                    "summary": summary_digest,
                }
            ),
        )
        artifact_subject = (
            SubjectRef(
                SubjectKind.ARTIFACT,
                deterministic_id("artifact:ollama", content_digest),
                digest=content_digest,
            )
            if content_digest
            else None
        )

        details = raw.get("details")
        details_map = details if isinstance(details, Mapping) else {}
        format_value = _optional_string(details_map.get("format"))
        family = _optional_string(details_map.get("family"))
        families_value = details_map.get("families")
        families = [item for item in families_value if isinstance(item, str)] if isinstance(families_value, list) else []
        family_labels = tuple(sorted(set(([family] if family else []) + families)))
        parameter_size = _optional_string(details_map.get("parameter_size"))
        quantization = _optional_string(details_map.get("quantization_level"))
        aliases = tuple(sorted(set(item for item in (name, model_alias) if item)))

        summary_evidence = factory.create(
            kind=EvidenceKind.RUNTIME_OBSERVATION,
            level=EvidenceLevel.DETECTED_FROM_RUNTIME,
            subject=deployment_subject,
            observation_key="deployment.model_summary",
            observed_value=normalized_raw,
            source_uri=f"{self.client.endpoint}/api/tags",
            source_digest=tags_digest,
            locator=f"/models/{index}",
            outcome=EvidenceOutcome.NOT_APPLICABLE,
        )
        evidence_items = [summary_evidence]
        if content_digest:
            digest_evidence = factory.create(
                kind=EvidenceKind.RUNTIME_OBSERVATION,
                level=EvidenceLevel.DETECTED_FROM_RUNTIME,
                subject=deployment_subject,
                observation_key="deployment.content_digest",
                observed_value=content_digest,
                source_uri=f"{self.client.endpoint}/api/tags",
                source_digest=tags_digest,
                locator=f"/models/{index}/digest",
                outcome=EvidenceOutcome.NOT_APPLICABLE,
            )
            evidence_items.append(digest_evidence)

        return (
            DiscoveredModelRecord(
                model_subject=model_subject,
                deployment_subject=deployment_subject,
                artifact_subject=artifact_subject,
                runtime_subject=runtime.subject,
                runtime_reference=runtime_reference,
                aliases=aliases,
                content_digest=content_digest,
                artifact_format=format_value,
                size_bytes=_optional_int(raw.get("size")),
                parameter_size_label=parameter_size,
                quantization_label=quantization,
                family_labels=family_labels,
                modified_at=_optional_string(raw.get("modified_at")),
                identity_status="CONTENT_ADDRESSED" if content_digest else "PROVISIONAL",
                raw_summary=normalized_raw if isinstance(normalized_raw, dict) else {},
                source_digest=summary_digest,
                evidence_ids=tuple(item.evidence_id for item in evidence_items),
            ),
            tuple(evidence_items),
        )

    async def discover(
        self, request: DiscoveryRequest, context: OperationContext
    ) -> AsyncIterator[DiscoveryObservation]:
        """Phase-1 port adapter over the richer Phase-2 result."""

        result = await self.discover_all()
        if result.runtime is not None:
            yield DiscoveryObservation(
                observation_id=deterministic_id(
                    "discovery", result.runtime.subject.subject_id
                ),
                resource_kind=ResourceKind.RUNTIME_INSTANCE,
                subject=result.runtime.subject,
                locator=result.runtime.endpoint,
                aliases=("ollama",),
                attributes={
                    "kind": result.runtime.kind,
                    "version": result.runtime.version,
                    "locality": result.runtime.locality.value,
                },
                evidence_ids=result.runtime.evidence_ids,
                completeness=result.completeness,
            )
        for model in result.models:
            yield DiscoveryObservation(
                observation_id=deterministic_id(
                    "discovery", model.deployment_subject.subject_id
                ),
                resource_kind=ResourceKind.MODEL_DEPLOYMENT,
                subject=model.deployment_subject,
                locator=f"{self.client.endpoint}/api/show",
                aliases=model.aliases,
                attributes={
                    "runtime_reference": model.runtime_reference,
                    "content_digest": model.content_digest,
                    "format": model.artifact_format,
                    "identity_status": model.identity_status,
                },
                evidence_ids=model.evidence_ids,
                completeness=result.completeness,
                parent=result.runtime.subject if result.runtime else None,
            )


def _problem(exc: OllamaClientError, stage: WorkflowStage) -> ProblemDetails:
    return ProblemDetails(
        code=exc.code,
        stage=stage,
        message=str(exc),
        retryable=exc.retryable,
        remediation=(
            "Verify the configured Ollama endpoint and retry."
            if exc.retryable
            else "Inspect the runtime response without inventing missing fields."
        ,),
        details={"status_code": exc.status_code},
    )
