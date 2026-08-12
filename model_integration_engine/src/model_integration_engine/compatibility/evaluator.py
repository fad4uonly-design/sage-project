"""Generic evidence-backed compatibility evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import TargetSystemProfile
from ..domain import (
    CapabilityClaim,
    CompatibilityAssessment,
    CompatibilityStatus,
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    EvidenceRecord,
    RequirementAssessment,
    RequirementStatus,
    SubjectRef,
    SupportState,
    ValidationState,
)
from ..evidence import EvidenceFactory, deterministic_id, sha256_digest, utc_now


@dataclass(frozen=True, slots=True)
class CompatibilityEvaluationResult:
    assessment: CompatibilityAssessment
    evidence: tuple[EvidenceRecord, ...]
    reasons: tuple[str, ...]
    external_label: str


@dataclass(slots=True)
class GenericCompatibilityEvaluator:
    policy_version: str = "compatibility-policy-0.2.0"
    clock: callable = utc_now

    def evaluate(
        self,
        *,
        deployment: SubjectRef,
        runtime: SubjectRef,
        adapter_id: str,
        target: TargetSystemProfile,
        claims: tuple[CapabilityClaim, ...],
        required_permissions: tuple[str, ...],
    ) -> CompatibilityEvaluationResult:
        claims_by_key: dict[str, list[CapabilityClaim]] = {}
        for claim in claims:
            claims_by_key.setdefault(claim.capability_key, []).append(claim)

        requirements = []
        blockers = []
        unknowns = []
        reasons = []
        parent_evidence_ids = []
        has_adapter_condition = False

        for requirement in target.requirements:
            candidates = claims_by_key.get(requirement.capability_key or "", [])
            evidence_ids = tuple(
                dict.fromkeys(
                    evidence_id
                    for claim in candidates
                    for evidence_id in claim.evidence_ids
                )
            )
            parent_evidence_ids.extend(evidence_ids)
            validated = [
                claim
                for claim in candidates
                if claim.validation is ValidationState.VALIDATED
                and claim.support in {SupportState.SUPPORTED, SupportState.PARTIAL}
            ]
            negatives = [
                claim
                for claim in candidates
                if claim.support is SupportState.NOT_SUPPORTED
            ]
            if validated:
                adapter_required = bool(requirement.parameters.get("requires_adapter"))
                status = (
                    RequirementStatus.SATISFIED_WITH_ADAPTER
                    if adapter_required
                    else RequirementStatus.SATISFIED
                )
                has_adapter_condition = has_adapter_condition or adapter_required
                reason = (
                    f"{requirement.requirement_id} is validated through adapter {adapter_id}."
                    if adapter_required
                    else f"{requirement.requirement_id} has validated supporting evidence."
                )
                adapter_obligations = (
                    (f"Use adapter {adapter_id} under its recorded configuration.",)
                    if adapter_required
                    else ()
                )
                remediation = ()
            elif negatives:
                status = RequirementStatus.UNSATISFIED
                reason = f"{requirement.requirement_id} has affirmative negative evidence."
                adapter_obligations = ()
                remediation = ("Select another deployment or revise the target requirement.",)
                if requirement.mandatory:
                    blockers.append(requirement.requirement_id)
            else:
                status = RequirementStatus.UNKNOWN
                reason = (
                    f"{requirement.requirement_id} lacks validated, unambiguous evidence."
                )
                adapter_obligations = ()
                remediation = ("Run the required safe validation probe.",)
                if requirement.mandatory:
                    unknowns.append(requirement.requirement_id)
            reasons.append(reason)
            requirements.append(
                RequirementAssessment(
                    requirement_id=requirement.requirement_id,
                    description=requirement.description,
                    mandatory=requirement.mandatory,
                    status=status,
                    evidence_ids=evidence_ids,
                    adapter_obligations=adapter_obligations,
                    remediation=remediation,
                    risks=(),
                )
            )

        if blockers:
            status = CompatibilityStatus.INCOMPATIBLE
            external_label = "INCOMPATIBLE"
        elif unknowns:
            status = CompatibilityStatus.UNKNOWN
            external_label = "UNKNOWN"
        elif has_adapter_condition:
            status = CompatibilityStatus.COMPATIBLE_WITH_ADAPTER
            external_label = "CONDITIONALLY_COMPATIBLE"
        else:
            status = CompatibilityStatus.COMPATIBLE
            external_label = "COMPATIBLE"

        assessment = CompatibilityAssessment(
            assessment_id=deterministic_id(
                "compatibility",
                deployment.subject_id,
                runtime.subject_id,
                adapter_id,
                target.profile_digest,
                self.policy_version,
                status.value,
            ),
            subject=deployment,
            target=target.target,
            target_profile_digest=target.profile_digest,
            status=status,
            requirements=tuple(requirements),
            blockers=tuple(blockers),
            unknowns=tuple(unknowns),
            required_permissions=required_permissions,
            policy_version=self.policy_version,
        )

        factory = EvidenceFactory(
            "mie.compatibility.generic", "0.2.0", self.clock
        )
        unique_parents = tuple(dict.fromkeys(parent_evidence_ids))
        if unique_parents:
            overall_evidence = factory.create(
                kind=EvidenceKind.DERIVATION,
                level=EvidenceLevel.INFERRED,
                subject=deployment,
                observation_key="compatibility.overall",
                observed_value={
                    "status": status.value,
                    "external_label": external_label,
                    "target_profile_digest": target.profile_digest,
                    "adapter_id": adapter_id,
                    "reasons": reasons,
                },
                source_uri=f"urn:mie:compatibility-policy:{self.policy_version}",
                source_digest=sha256_digest(
                    {
                        "policy": self.policy_version,
                        "target": target.profile_digest,
                    }
                ),
                locator="overall",
                outcome=EvidenceOutcome.NOT_APPLICABLE,
                derived_from=unique_parents,
            )
        else:
            overall_evidence = factory.create(
                kind=EvidenceKind.STATIC_ANALYSIS,
                level=EvidenceLevel.UNKNOWN,
                subject=deployment,
                observation_key="compatibility.overall",
                observed_value={
                    "status": status.value,
                    "external_label": external_label,
                    "reasons": reasons,
                },
                source_uri=f"urn:mie:compatibility-policy:{self.policy_version}",
                source_digest=sha256_digest({"policy": self.policy_version}),
                locator="overall",
                outcome=EvidenceOutcome.INCONCLUSIVE,
            )
        return CompatibilityEvaluationResult(
            assessment=assessment,
            evidence=(overall_evidence,),
            reasons=tuple(reasons),
            external_label=external_label,
        )
