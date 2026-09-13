import pytest
from sage_research.domain.confidence import Confidence, UncertaintyDomain, UncertaintyProfile
from sage_research.domain.knowledge import (
    EvidenceCategory,
    EvidenceRef,
    EvidenceStrength,
    GeneralizationState,
    KnowledgeLayer,
    KnowledgeRecord,
    KnowledgeReference,
    KnowledgeState,
    ReplicationStatus,
    cap_confidence,
    stable_knowledge_id,
)


def _evidence() -> EvidenceRef:
    return EvidenceRef(
        source_kind="architecture_inspection",
        source_id="rpt-test",
        category=EvidenceCategory.ARCHITECTURE,
        strength=EvidenceStrength.CONFIRMED,
        description="test",
        timestamp_utc="2026-01-01T00:00:00+00:00",
    )


def _record(
    *,
    claim: str = "x == 1",
    state: KnowledgeState = KnowledgeState.CONFIRMED,
    profile: dict | None = None,
    confidence: Confidence | None = None,
    evidence: tuple = (_evidence(),),
    dependencies: tuple = (),
) -> KnowledgeRecord:
    profile = profile or {
        UncertaintyDomain.MODEL: Confidence(1.0),
        UncertaintyDomain.METHOD: Confidence(0.95),
    }
    return KnowledgeRecord(
        knowledge_id=stable_knowledge_id("s", claim),
        layer=KnowledgeLayer.MODEL,
        subject="s",
        claim=claim,
        state=state,
        uncertainty=UncertaintyProfile(profile),
        confidence=confidence or UncertaintyProfile(profile).ceiling,
        replication=ReplicationStatus.SINGLE_OBSERVATION,
        generalization=GeneralizationState.THIS_SPECIMEN,
        evidence=evidence,
        counterevidence=(),
        dependencies=dependencies,
        system_version="0.0.0-test",
        created_utc="2026-01-01T00:00:00+00:00",
        provenance="unit_test",
    )


def test_stable_knowledge_id_is_deterministic_and_content_based():
    a = stable_knowledge_id("pythia/pythia-70m@default", "hidden_size == 512")
    b = stable_knowledge_id("pythia/pythia-70m@default", "hidden_size == 512")
    c = stable_knowledge_id("pythia/pythia-70m@default", "hidden_size == 768")
    assert a == b
    assert a != c
    assert a.startswith("kn-")


def test_confirmed_state_requires_evidence():
    with pytest.raises(ValueError):
        _record(state=KnowledgeState.CONFIRMED, evidence=())


def test_hypothesis_state_allows_no_evidence():
    record = _record(state=KnowledgeState.HYPOTHESIS, evidence=())
    assert record.state == KnowledgeState.HYPOTHESIS


def test_confidence_cannot_exceed_ceiling():
    profile = {
        UncertaintyDomain.MODEL: Confidence(1.0),
        UncertaintyDomain.METHOD: Confidence(0.9),
    }
    with pytest.raises(ValueError):
        _record(profile=profile, confidence=Confidence(0.95))


def test_cap_confidence_weakest_dependency():
    profile = UncertaintyProfile(
        {
            UncertaintyDomain.MODEL: Confidence(1.0),
            UncertaintyDomain.METHOD: Confidence(0.95),
        }
    )
    assert cap_confidence(profile, ()) == Confidence(0.95)
    assert cap_confidence(profile, (Confidence(0.8),)) == Confidence(0.8)
    assert cap_confidence(profile, (Confidence(0.8), Confidence(0.9))) == Confidence(0.8)


def test_round_trip():
    dep = KnowledgeReference("kn-abc", KnowledgeLayer.MODEL)
    record = _record(dependencies=(dep,))
    restored = KnowledgeRecord.from_dict(record.to_dict())
    assert restored == record
    assert restored.dependencies == (dep,)
