"""Evidence-backed, model-agnostic capability hypothesis generation."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import (
    CapabilityClaim,
    CapabilityClass,
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    EvidenceRecord,
    SupportState,
    ValidationState,
)
from ..evidence import EvidenceFactory, deterministic_id, sha256_digest, utc_now
from ..phase2_models import DiscoveredModelRecord, ModelInspectionResult, RuntimeRecord


@dataclass(frozen=True, slots=True)
class CapabilityHypothesisResult:
    claims: tuple[CapabilityClaim, ...]
    evidence: tuple[EvidenceRecord, ...]


@dataclass(slots=True)
class GenericCapabilityHypothesisDetector:
    long_context_threshold: int = 32_768
    policy_version: str = "capability-hypotheses-0.2.0"
    clock: callable = utc_now

    def detect(
        self,
        *,
        runtime: RuntimeRecord,
        model: DiscoveredModelRecord,
        inspection: ModelInspectionResult,
        available_evidence: tuple[EvidenceRecord, ...],
    ) -> CapabilityHypothesisResult:
        factory = EvidenceFactory(
            "mie.capabilities.generic-hypotheses",
            "0.2.0",
            self.clock,
        )
        details = inspection.details
        declared = set(details.declared_capabilities if details else ())
        evidence_by_key: dict[str, list[EvidenceRecord]] = {}
        for item in available_evidence:
            evidence_by_key.setdefault(item.observation_key, []).append(item)

        created_evidence: list[EvidenceRecord] = []
        claims: list[CapabilityClaim] = []

        declaration_evidence = evidence_by_key.get("capabilities", [])
        declaration_ids = tuple(item.evidence_id for item in declaration_evidence)
        declaration_levels = tuple(sorted({item.level for item in declaration_evidence}, key=str))
        fallback_parent_ids = tuple(
            item.evidence_id
            for item in available_evidence
            if item.subject.subject_id
            in {model.deployment_subject.subject_id, runtime.subject.subject_id}
        )[:2]

        def inferred_evidence(
            capability_key: str,
            subject,
            rule: str,
            parent_ids: tuple[str, ...] = (),
        ) -> EvidenceRecord:
            if parent_ids:
                item = factory.create(
                    kind=EvidenceKind.DERIVATION,
                    level=EvidenceLevel.INFERRED,
                    subject=subject,
                    observation_key=f"hypothesis.{capability_key}",
                    observed_value={"rule": rule, "status": "hypothesis"},
                    source_uri=f"urn:mie:capability-rule:{rule}",
                    source_digest=sha256_digest(
                        {"policy": self.policy_version, "rule": rule}
                    ),
                    locator=rule,
                    outcome=EvidenceOutcome.NOT_APPLICABLE,
                    derived_from=parent_ids,
                )
            else:
                item = factory.create(
                    kind=EvidenceKind.STATIC_ANALYSIS,
                    level=EvidenceLevel.INFERRED,
                    subject=subject,
                    observation_key=f"hypothesis.{capability_key}",
                    observed_value={"rule": rule, "status": "hypothesis"},
                    source_uri=f"urn:mie:capability-rule:{rule}",
                    source_digest=sha256_digest(
                        {"policy": self.policy_version, "rule": rule}
                    ),
                    locator=rule,
                    outcome=EvidenceOutcome.NOT_APPLICABLE,
                )
            created_evidence.append(item)
            return item

        def add_claim(
            capability_key: str,
            capability_class: CapabilityClass,
            subject,
            *,
            support: SupportState,
            evidence_ids: tuple[str, ...],
            levels: tuple[EvidenceLevel, ...],
            parameters=None,
            limitations=(),
        ) -> None:
            claims.append(
                CapabilityClaim(
                    claim_id=deterministic_id(
                        "claim", subject.subject_id, capability_key, self.policy_version
                    ),
                    capability_key=capability_key,
                    capability_class=capability_class,
                    subject=subject,
                    support=support,
                    validation=ValidationState.UNVALIDATED,
                    evidence_levels=levels,
                    evidence_ids=evidence_ids,
                    parameters=parameters or {},
                    limitations=limitations,
                    contradictions=(),
                    policy_version=self.policy_version,
                    assessed_at=self.clock(),
                )
            )

        declarations = {
            "generation.text": "completion",
            "tools.function_calling": "tools",
            "modality.vision.input": "vision",
            "generation.embeddings": "embedding",
            "output.thinking_channel": "thinking",
        }
        for capability_key, declaration in declarations.items():
            declared_match = declaration in declared or (
                declaration == "embedding" and "embeddings" in declared
            )
            if declared_match and declaration_ids:
                add_claim(
                    capability_key,
                    CapabilityClass.MODEL_CAPABILITY,
                    model.deployment_subject,
                    support=SupportState.SUPPORTED,
                    evidence_ids=declaration_ids,
                    levels=declaration_levels
                    or (EvidenceLevel.DETECTED_FROM_METADATA,),
                    parameters={"runtime_declaration": declaration},
                    limitations=(
                        "Runtime/model-detail declaration only; behavior is not validated.",
                    ),
                )
            else:
                item = inferred_evidence(
                    capability_key,
                    model.deployment_subject,
                    f"declaration-absent-does-not-prove-negative:{declaration}",
                    fallback_parent_ids,
                )
                add_claim(
                    capability_key,
                    CapabilityClass.MODEL_CAPABILITY,
                    model.deployment_subject,
                    support=SupportState.UNKNOWN,
                    evidence_ids=(item.evidence_id,),
                    levels=(EvidenceLevel.INFERRED,),
                    limitations=(
                        "No affirmative declaration or behavioral validation was found.",
                    ),
                )

        template_parent_ids = tuple(
            item.evidence_id
            for item in available_evidence
            if item.observation_key == "template"
        )
        instruction_item = inferred_evidence(
            "instruction.following",
            model.deployment_subject,
            "chat-template-suggests-instruction-interface"
            if details and details.template is not None
            else "instruction-behavior-unknown",
            template_parent_ids or fallback_parent_ids,
        )
        add_claim(
            "instruction.following",
            CapabilityClass.MODEL_CAPABILITY,
            model.deployment_subject,
            support=SupportState.UNKNOWN,
            evidence_ids=(instruction_item.evidence_id,),
            levels=(EvidenceLevel.INFERRED,),
            limitations=("Requires behavioral validation.",),
        )

        reasoning_parents = declaration_ids or fallback_parent_ids
        reasoning_item = inferred_evidence(
            "reasoning.general",
            model.deployment_subject,
            "thinking-channel-is-not-reasoning-validation"
            if "thinking" in declared
            else "reasoning-behavior-unknown",
            reasoning_parents,
        )
        add_claim(
            "reasoning.general",
            CapabilityClass.MODEL_CAPABILITY,
            model.deployment_subject,
            support=SupportState.UNKNOWN,
            evidence_ids=(reasoning_item.evidence_id,),
            levels=(EvidenceLevel.INFERRED,),
            limitations=("Reasoning outcomes have not been tested.",),
        )

        structured_item = inferred_evidence(
            "output.schema_constrained",
            model.deployment_subject,
            "runtime-format-parameter-does-not-prove-model-adherence",
            fallback_parent_ids,
        )
        add_claim(
            "output.schema_constrained",
            CapabilityClass.MODEL_CAPABILITY,
            model.deployment_subject,
            support=SupportState.UNKNOWN,
            evidence_ids=(structured_item.evidence_id,),
            levels=(EvidenceLevel.INFERRED,),
            limitations=("Requires schema-conformance probe.",),
        )

        streaming_item = inferred_evidence(
            "protocol.streaming",
            runtime.subject,
            "adapter-has-stream-operation-runtime-not-yet-probed",
            fallback_parent_ids,
        )
        add_claim(
            "protocol.streaming",
            CapabilityClass.RUNTIME_CAPABILITY,
            runtime.subject,
            support=SupportState.UNKNOWN,
            evidence_ids=(streaming_item.evidence_id,),
            levels=(EvidenceLevel.INFERRED,),
            limitations=("Protocol streaming has not been validated on this runtime.",),
        )

        context_parent_ids = tuple(
            item.evidence_id
            for item in available_evidence
            if item.observation_key.endswith(".context_length")
        )
        if details and details.context_length is not None and context_parent_ids:
            long_support = (
                SupportState.SUPPORTED
                if details.context_length >= self.long_context_threshold
                else SupportState.UNKNOWN
            )
            add_claim(
                "context.long",
                CapabilityClass.MODEL_CAPABILITY,
                model.deployment_subject,
                support=long_support,
                evidence_ids=context_parent_ids,
                levels=(EvidenceLevel.DETECTED_FROM_METADATA,),
                parameters={
                    "declared_context_length": details.context_length,
                    "threshold": self.long_context_threshold,
                },
                limitations=(
                    "Declared context metadata only; usable context is not validated.",
                ),
            )
        else:
            context_item = inferred_evidence(
                "context.long",
                model.deployment_subject,
                "context-length-unknown",
                fallback_parent_ids,
            )
            add_claim(
                "context.long",
                CapabilityClass.MODEL_CAPABILITY,
                model.deployment_subject,
                support=SupportState.UNKNOWN,
                evidence_ids=(context_item.evidence_id,),
                levels=(EvidenceLevel.INFERRED,),
                limitations=("No unambiguous context length was observed.",),
            )

        claims.sort(key=lambda item: (item.capability_key, item.subject.subject_id))
        return CapabilityHypothesisResult(
            claims=tuple(claims), evidence=tuple(created_evidence)
        )
