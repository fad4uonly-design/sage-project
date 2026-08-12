from __future__ import annotations

from datetime import UTC, datetime

import pytest

from model_integration_engine.domain import (
    AdapterCandidate,
    AdapterOrigin,
    ApprovalEvent,
    ApprovalScope,
    ApprovalState,
    CapabilityClaim,
    CapabilityClass,
    CompatibilityAssessment,
    CompatibilityStatus,
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    EvidenceRecord,
    RequirementAssessment,
    RequirementStatus,
    SourceRef,
    SubjectKind,
    SubjectRef,
    SupportState,
    TrustState,
    ValidationState,
)

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
DEPLOYMENT = SubjectRef(SubjectKind.DEPLOYMENT, "deployment:test", digest="sha256:x")


def test_validated_claim_requires_test_level() -> None:
    with pytest.raises(ValueError, match="VALIDATED_BY_TEST"):
        CapabilityClaim(
            claim_id="claim-1",
            capability_key="generation.text",
            capability_class=CapabilityClass.MODEL_CAPABILITY,
            subject=DEPLOYMENT,
            support=SupportState.SUPPORTED,
            validation=ValidationState.VALIDATED,
            evidence_levels=(EvidenceLevel.INFERRED,),
            evidence_ids=("ev-1",),
            assessed_at=NOW,
        )


def test_validated_claim_is_registry_eligible() -> None:
    claim = CapabilityClaim(
        claim_id="claim-1",
        capability_key="generation.text",
        capability_class=CapabilityClass.MODEL_CAPABILITY,
        subject=DEPLOYMENT,
        support=SupportState.SUPPORTED,
        validation=ValidationState.VALIDATED,
        evidence_levels=(EvidenceLevel.VALIDATED_BY_TEST,),
        evidence_ids=("ev-test",),
        assessed_at=NOW,
    )
    assert claim.is_registry_eligible


def test_not_supported_requires_affirmative_negative_evidence() -> None:
    with pytest.raises(ValueError, match="affirmative negative"):
        CapabilityClaim(
            claim_id="claim-vision",
            capability_key="modality.vision.input",
            capability_class=CapabilityClass.MODEL_CAPABILITY,
            subject=DEPLOYMENT,
            support=SupportState.NOT_SUPPORTED,
            validation=ValidationState.UNVALIDATED,
            evidence_levels=(EvidenceLevel.UNKNOWN,),
            evidence_ids=("ev-missing-field",),
        )


def test_unknown_claim_can_remain_evidence_free() -> None:
    claim = CapabilityClaim(
        claim_id="claim-unknown",
        capability_key="task.coding",
        capability_class=CapabilityClass.MODEL_CAPABILITY,
        subject=DEPLOYMENT,
        support=SupportState.UNKNOWN,
        validation=ValidationState.UNVALIDATED,
        evidence_levels=(EvidenceLevel.UNKNOWN,),
        evidence_ids=(),
    )
    assert not claim.is_registry_eligible


def test_test_validation_evidence_must_pass() -> None:
    with pytest.raises(ValueError, match="passing outcome"):
        EvidenceRecord(
            evidence_id="ev-test",
            kind=EvidenceKind.TEST_RESULT,
            level=EvidenceLevel.VALIDATED_BY_TEST,
            subject=DEPLOYMENT,
            observation_key="generation.text",
            observed_value=False,
            source=SourceRef("evidence://test"),
            collector_id="test",
            collector_version="1",
            collected_at=NOW,
            outcome=EvidenceOutcome.FAIL,
        )


def test_unknown_mandatory_requirement_blocks_compatible_status() -> None:
    target = SubjectRef(SubjectKind.TARGET, "target:synthetic")
    requirement = RequirementAssessment(
        requirement_id="req-stream",
        description="Streaming",
        mandatory=True,
        status=RequirementStatus.UNKNOWN,
        evidence_ids=(),
    )
    with pytest.raises(ValueError, match="unknown mandatory"):
        CompatibilityAssessment(
            assessment_id="compat-1",
            subject=DEPLOYMENT,
            target=target,
            target_profile_digest="sha256:target",
            status=CompatibilityStatus.COMPATIBLE,
            requirements=(requirement,),
            blockers=(),
            unknowns=("req-stream",),
            required_permissions=(),
            policy_version="1",
        )


def test_generated_adapter_begins_untrusted() -> None:
    with pytest.raises(ValueError, match="begin untrusted"):
        AdapterCandidate(
            adapter_id="adapter-generated",
            adapter_version="0",
            origin=AdapterOrigin.GENERATED,
            trust_state=TrustState.REVIEW_REQUIRED,
            contract_version="1",
            source_manifest_digest="sha256:source",
            configuration_digest=None,
            supported_operations=("chat",),
            required_permissions=(),
        )


def test_approved_event_requires_audit_reference() -> None:
    scope = ApprovalScope(
        package_digest="sha256:package",
        proposed_change_set_digest="sha256:changes",
        target_profile_digest="sha256:target",
        permission_set_digest="sha256:permissions",
        policy_version="1",
    )
    with pytest.raises(ValueError, match="audit reference"):
        ApprovalEvent(
            event_id="approval-1",
            state=ApprovalState.APPROVED,
            actor_id="human:test",
            decided_at=NOW,
            scope=scope,
            audit_reference=None,
        )
