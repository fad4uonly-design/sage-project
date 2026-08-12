"""Smallest read-only Phase 2 orchestration path.

The workflow terminates at a validated DRAFT package with approval NOT_REQUESTED.
There is deliberately no application or registry call.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..capabilities.delta import (
    CapabilityDeltaResult,
    GenericCapabilityDeltaComparator,
)
from ..capabilities.hypotheses import GenericCapabilityHypothesisDetector
from ..compatibility.evaluator import GenericCompatibilityEvaluator
from ..contracts import OperationContext, TargetRequirement, TargetSystemProfile
from ..domain import (
    AdapterCandidate,
    AdapterOrigin,
    EvidenceRecord,
    JSONValue,
    ProblemDetails,
    SubjectKind,
    SubjectRef,
    TestOutcome,
    TrustState,
    ValidationState,
    WorkflowStage,
)
from ..evidence import deterministic_id, sha256_digest, utc_now
from ..inspectors.gguf import GGUFArray, GGUFMetadataValue
from ..inspectors.template import GenericChatTemplateInspector
from ..inspectors.tokenizer import GenericTokenizerInspector
from ..packaging.draft import (
    DraftIntegrationPackageBuilder,
    DraftPackageArtifact,
    DraftPackageInput,
)
from ..phase2_models import (
    DiscoveryResult,
    EnvironmentInfo,
    ModelInspectionResult,
)
from ..plugins.ollama.adapter import GenericOllamaAdapter, OllamaAdapterConfig
from ..plugins.ollama.client import JsonTransport, OllamaClient
from ..plugins.ollama.discovery import OllamaDiscoveryProvider
from ..plugins.ollama.inspection import OllamaModelInspector
from ..user_evidence import UserInputEvidenceCollector
from .probes import (
    MinimalProbePlanner,
    ProbeBatchResult,
    ProbeCoordinator,
    ProbeExecutionBackend,
    ProbeKind,
    SafeProbeHarness,
)


@dataclass(frozen=True, slots=True)
class VerticalSliceConfig:
    endpoint: str
    model_reference: str | None
    target_profile: TargetSystemProfile
    environment: EnvironmentInfo
    live_validation: bool = False
    timeout_seconds: float = 10.0
    include_operational_probes: bool = False
    user_evidence_document: Mapping[str, JSONValue] | None = None
    additional_evidence: tuple[EvidenceRecord, ...] = ()
    registry_snapshot: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class VerticalSliceResult:
    state: str
    discovery: DiscoveryResult
    inspection: ModelInspectionResult | None
    probes: ProbeBatchResult | None
    package: DraftPackageArtifact | None
    problem: ProblemDetails | None
    capability_delta: CapabilityDeltaResult | None = None


@dataclass(slots=True)
class Phase2VerticalSliceEngine:
    transport: JsonTransport
    probe_backend: ProbeExecutionBackend
    package_builder: DraftIntegrationPackageBuilder
    clock: callable = utc_now
    engine_version: str = "0.2.0a0"

    async def run(
        self,
        config: VerticalSliceConfig,
        context: OperationContext,
    ) -> VerticalSliceResult:
        client = OllamaClient(
            endpoint=config.endpoint,
            transport=self.transport,
            timeout_seconds=config.timeout_seconds,
        )
        discovery_provider = OllamaDiscoveryProvider(client=client, clock=self.clock)
        discovery = await discovery_provider.discover_all()
        if discovery.runtime is None or discovery.problem is not None:
            return VerticalSliceResult(
                state="FAILED_RECOVERABLE"
                if discovery.problem and discovery.problem.retryable
                else "FAILED",
                discovery=discovery,
                inspection=None,
                probes=None,
                package=None,
                problem=discovery.problem,
            )

        selected, selection_problem = _select_model(
            discovery, config.model_reference
        )
        if selection_problem is not None or selected is None:
            return VerticalSliceResult(
                state="FAILED",
                discovery=discovery,
                inspection=None,
                probes=None,
                package=None,
                problem=selection_problem,
            )

        inspector = OllamaModelInspector(client=client, clock=self.clock)
        inspection = await inspector.inspect_model(selected)
        if inspection.details is None or inspection.problem is not None:
            return VerticalSliceResult(
                state="FAILED_RECOVERABLE"
                if inspection.problem and inspection.problem.retryable
                else "FAILED",
                discovery=discovery,
                inspection=inspection,
                probes=None,
                package=None,
                problem=inspection.problem,
            )

        subject_map = {
            SubjectKind.RUNTIME: discovery.runtime.subject,
            SubjectKind.DEPLOYMENT: selected.deployment_subject,
            SubjectKind.MODEL: selected.model_subject,
        }
        if selected.artifact_subject is not None:
            subject_map[SubjectKind.ARTIFACT] = selected.artifact_subject
        user_evidence = UserInputEvidenceCollector(clock=self.clock).collect(
            config.user_evidence_document,
            subjects=subject_map,
            default_environment_id=config.environment.environment_id,
        )
        runtime_metadata_extensions = _runtime_metadata_extension_evidence(
            inspection,
            subject=selected.artifact_subject or selected.deployment_subject,
            source_uri=f"{config.endpoint.rstrip('/')}/api/show",
            clock=self.clock,
        )

        # User input is retained in the evidence set but is deliberately not an
        # input to automated capability promotion. Only live collectors and
        # direct inspectors contribute to the generic hypotheses below.
        initial_evidence = discovery.evidence + inspection.evidence
        hypotheses = GenericCapabilityHypothesisDetector(clock=self.clock).detect(
            runtime=discovery.runtime,
            model=selected,
            inspection=inspection,
            available_evidence=initial_evidence,
        )

        configuration_digest = sha256_digest(
            {
                "runtime": discovery.runtime.subject.digest,
                "deployment": selected.deployment_subject.digest,
                "model_reference": selected.runtime_reference,
                "runtime_owns_template": True,
                "template_digest": inspection.details.template_digest,
                "adapter_contract": "normalized-inference-0.1.0",
            }
        )
        adapter_config = OllamaAdapterConfig(
            runtime=discovery.runtime.subject,
            deployment=selected.deployment_subject,
            model_reference=selected.runtime_reference,
            configuration_digest=configuration_digest,
            runtime_owns_template=True,
        )
        adapter = GenericOllamaAdapter(client=client, config=adapter_config)
        plan = MinimalProbePlanner().plan(
            deployment=selected.deployment_subject,
            runtime=discovery.runtime.subject,
            adapter_id=adapter.descriptor.plugin_id,
            configuration_digest=configuration_digest,
            environment_id=config.environment.environment_id,
            hypotheses=hypotheses.claims,
            include_operational_probes=config.include_operational_probes,
        )
        probes = await ProbeCoordinator(
            backend=self.probe_backend, clock=self.clock
        ).execute(
            plan=plan,
            harness=SafeProbeHarness(),
            adapter=adapter,
            context=context,
            hypotheses=hypotheses.claims,
        )

        passed_probe_evidence = tuple(
            result.evidence_id
            for result in probes.results
            if result.raw.outcome is TestOutcome.PASS
        )
        basic_passed = any(
            result.raw.kind is ProbeKind.BASIC_GENERATION
            and result.raw.outcome is TestOutcome.PASS
            for result in probes.results
        )
        adapter_candidate = AdapterCandidate(
            adapter_id=adapter.descriptor.plugin_id,
            adapter_version=adapter.descriptor.plugin_version,
            origin=AdapterOrigin.CONFIGURED,
            trust_state=TrustState.REVIEW_REQUIRED,
            contract_version=adapter.descriptor.contract_version,
            source_manifest_digest=adapter.adapter_subject.digest,
            configuration_digest=configuration_digest,
            supported_operations=(
                "chat",
                "stream",
                "structured_output",
                "tools",
            ),
            required_permissions=(f"network:{client.endpoint}",),
            validation=ValidationState.VALIDATED
            if basic_passed and probes.problem is None
            else ValidationState.UNVALIDATED,
            evidence_ids=passed_probe_evidence,
            limitations=(
                "Validated only for operations represented by passing probe evidence.",
            ),
        )

        compatibility = GenericCompatibilityEvaluator(clock=self.clock).evaluate(
            deployment=selected.deployment_subject,
            runtime=discovery.runtime.subject,
            adapter_id=adapter_candidate.adapter_id,
            target=config.target_profile,
            claims=probes.claims,
            required_permissions=adapter_candidate.required_permissions,
        )
        capability_delta = GenericCapabilityDeltaComparator().compare(
            probes.claims, config.registry_snapshot
        )
        all_evidence = _deduplicate_evidence(
            discovery.evidence
            + inspection.evidence
            + hypotheses.evidence
            + probes.evidence
            + compatibility.evidence
            + runtime_metadata_extensions
            + user_evidence
            + config.additional_evidence
        )
        package = self.package_builder.build(
            DraftPackageInput(
                run_id=context.run_id,
                created_at=self.clock(),
                engine_version=self.engine_version,
                runtime=discovery.runtime,
                model=selected,
                inspection=inspection,
                adapter=adapter_candidate,
                adapter_config=adapter_config,
                capabilities=probes.claims,
                evidence=all_evidence,
                probes=probes,
                compatibility=compatibility,
                target_profile=config.target_profile,
                environment=config.environment,
                live_validation=config.live_validation,
                capability_delta=capability_delta.package_document(),
            )
        )
        return VerticalSliceResult(
            state="DRAFT_PENDING_APPROVAL",
            discovery=discovery,
            inspection=inspection,
            probes=probes,
            package=package,
            problem=probes.problem,
            capability_delta=capability_delta,
        )


def default_target_profile() -> TargetSystemProfile:
    material = {
        "target_id": "target:synthetic-normalized-model-interface",
        "profile_version": "0.2.0",
        "contract": "normalized-inference-0.1.0",
        "requirements": [
            {"id": "text", "key": "generation.text", "mandatory": True},
            {"id": "instruction", "key": "instruction.following", "mandatory": True},
            {"id": "structured", "key": "output.schema_constrained", "mandatory": False},
            {"id": "stream", "key": "protocol.streaming", "mandatory": False},
            {"id": "tools", "key": "tools.function_calling", "mandatory": False},
        ],
    }
    target = SubjectRef(
        SubjectKind.TARGET,
        material["target_id"],
        version=material["profile_version"],
        digest=sha256_digest(material),
    )
    requirements = tuple(
        TargetRequirement(
            requirement_id=item["id"],
            description=f"Target requires {item['key']}",
            mandatory=item["mandatory"],
            capability_key=item["key"],
            parameters={"requires_adapter": True},
        )
        for item in material["requirements"]
    )
    return TargetSystemProfile(
        target=target,
        profile_version=material["profile_version"],
        profile_digest=target.digest or sha256_digest(material),
        normalized_contract_version=material["contract"],
        requirements=requirements,
        constraints={
            "local_first": True,
            "approval_required": True,
            "target_write_allowed": False,
        },
        regression_suite_ref="synthetic-target-regression@0.2.0",
        capability_snapshot_digest=sha256_digest(
            {"target": target.subject_id, "capabilities": []}
        ),
    )


def environment_info(
    *,
    environment_id: str,
    locality: str,
    sandbox_backend_id: str | None,
    attributes=None,
) -> EnvironmentInfo:
    return EnvironmentInfo(
        environment_id=environment_id,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        machine=platform.machine() or "unknown",
        runtime_endpoint_locality=locality,
        sandbox_backend_id=sandbox_backend_id,
        attributes=attributes or {},
    )


def _select_model(discovery: DiscoveryResult, requested: str | None):
    if requested is not None:
        matches = [
            model
            for model in discovery.models
            if requested == model.runtime_reference or requested in model.aliases
        ]
        if len(matches) == 1:
            return matches[0], None
        return None, ProblemDetails(
            code="MODEL_REFERENCE_NOT_FOUND"
            if not matches
            else "MODEL_REFERENCE_AMBIGUOUS",
            stage=WorkflowStage.DISCOVERED,
            message=(
                f"Configured model reference {requested!r} was not found."
                if not matches
                else f"Configured model reference {requested!r} is ambiguous."
            ),
            retryable=False,
            remediation=("Select an exact discovered runtime reference and content digest.",),
        )
    if len(discovery.models) == 1:
        return discovery.models[0], None
    return None, ProblemDetails(
        code="NO_MODELS_DISCOVERED"
        if not discovery.models
        else "MODEL_SELECTION_REQUIRED",
        stage=WorkflowStage.DISCOVERED,
        message=(
            "Ollama returned an empty model list."
            if not discovery.models
            else "Multiple deployments were discovered; explicit selection is required."
        ),
        retryable=False,
        remediation=("Install/select a model outside MIE, then rerun discovery.",),
    )


def _runtime_metadata_extension_evidence(
    inspection: ModelInspectionResult,
    *,
    subject: SubjectRef,
    source_uri: str,
    clock,
):
    """Reuse generic tokenizer/template inspectors over `/api/show` metadata.

    Runtime-returned metadata remains runtime-sourced metadata. Constructing the
    generic metadata wrappers here does not turn it into direct artifact-byte
    evidence or behavioral validation.
    """

    details = inspection.details
    if details is None:
        return ()
    metadata: dict[str, GGUFMetadataValue] = {}
    for key, value in details.model_info.items():
        if not key.startswith("tokenizer."):
            continue
        metadata[key] = _runtime_metadata_value(value)
    if details.template is not None:
        metadata["chat_template"] = GGUFMetadataValue("STRING", details.template)
    tokenizer = GenericTokenizerInspector(clock=clock).inspect(
        artifact=subject,
        metadata=metadata,
        source_uri=source_uri,
        source_digest=details.raw_response_digest,
    )
    template = GenericChatTemplateInspector(clock=clock).inspect(
        artifact=subject,
        metadata=metadata,
        source_uri=source_uri,
        source_digest=details.raw_response_digest,
    )
    return tokenizer.evidence + template.evidence


def _runtime_metadata_value(value: JSONValue) -> GGUFMetadataValue:
    if isinstance(value, list):
        retained = tuple(value[:4096])
        element_type = (
            type(retained[0]).__name__.upper() if retained else "UNKNOWN"
        )
        return GGUFMetadataValue(
            "ARRAY",
            GGUFArray(
                element_type=element_type,
                count=len(value),
                values=retained,
                materialized_count=len(retained),
            ),
        )
    return GGUFMetadataValue(type(value).__name__.upper(), value)


def _deduplicate_evidence(items):
    result = {}
    for item in items:
        result.setdefault(item.evidence_id, item)
    return tuple(result[key] for key in sorted(result))
