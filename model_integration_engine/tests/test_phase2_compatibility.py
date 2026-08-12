from __future__ import annotations

from datetime import UTC, datetime

from model_integration_engine.application.vertical_slice import default_target_profile
from model_integration_engine.compatibility.evaluator import GenericCompatibilityEvaluator
from model_integration_engine.domain import (
    CapabilityClaim,
    CapabilityClass,
    CompatibilityStatus,
    EvidenceLevel,
    SubjectKind,
    SubjectRef,
    SupportState,
    ValidationState,
)
from model_integration_engine.evidence import sha256_digest

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
DEPLOYMENT = SubjectRef(SubjectKind.DEPLOYMENT, "deployment:test", digest=sha256_digest("d"))
RUNTIME = SubjectRef(SubjectKind.RUNTIME, "runtime:test", digest=sha256_digest("r"))


def claim(key, support, validation, evidence_level):
    return CapabilityClaim(
        claim_id="claim:" + key,
        capability_key=key,
        capability_class=CapabilityClass.MODEL_CAPABILITY,
        subject=DEPLOYMENT,
        support=support,
        validation=validation,
        evidence_levels=(evidence_level,),
        evidence_ids=("evidence:" + key,),
        assessed_at=NOW,
    )


def test_unknown_mandatory_capability_blocks_compatibility() -> None:
    result = GenericCompatibilityEvaluator(clock=lambda: NOW).evaluate(
        deployment=DEPLOYMENT,
        runtime=RUNTIME,
        adapter_id="adapter:generic",
        target=default_target_profile(),
        claims=(
            claim(
                "generation.text",
                SupportState.SUPPORTED,
                ValidationState.UNVALIDATED,
                EvidenceLevel.DETECTED_FROM_METADATA,
            ),
        ),
        required_permissions=(),
    )
    assert result.assessment.status is CompatibilityStatus.UNKNOWN
    assert "text" in result.assessment.unknowns
    assert result.external_label == "UNKNOWN"


def test_affirmative_negative_mandatory_claim_is_incompatible() -> None:
    negative = claim(
        "generation.text",
        SupportState.NOT_SUPPORTED,
        ValidationState.FAILED,
        EvidenceLevel.NOT_SUPPORTED,
    )
    result = GenericCompatibilityEvaluator(clock=lambda: NOW).evaluate(
        deployment=DEPLOYMENT,
        runtime=RUNTIME,
        adapter_id="adapter:generic",
        target=default_target_profile(),
        claims=(negative,),
        required_permissions=(),
    )
    assert result.assessment.status is CompatibilityStatus.INCOMPATIBLE
    assert "text" in result.assessment.blockers


def test_validated_requirements_are_conditionally_compatible_through_adapter() -> None:
    claims = tuple(
        claim(
            key,
            SupportState.SUPPORTED,
            ValidationState.VALIDATED,
            EvidenceLevel.VALIDATED_BY_TEST,
        )
        for key in ("generation.text", "instruction.following")
    )
    result = GenericCompatibilityEvaluator(clock=lambda: NOW).evaluate(
        deployment=DEPLOYMENT,
        runtime=RUNTIME,
        adapter_id="adapter:generic",
        target=default_target_profile(),
        claims=claims,
        required_permissions=("network:fixture",),
    )
    assert result.assessment.status is CompatibilityStatus.COMPATIBLE_WITH_ADAPTER
    assert result.external_label == "CONDITIONALLY_COMPATIBLE"
    assert not result.assessment.blockers
    assert not result.assessment.unknowns
