from sage_research.domain.confidence import Confidence, UncertaintyDomain, UncertaintyProfile
from sage_research.domain.knowledge import (
    EvidenceCategory,
    EvidenceRef,
    EvidenceStrength,
    GeneralizationState,
    KnowledgeLayer,
    KnowledgeRecord,
    KnowledgeState,
    ReplicationStatus,
    stable_knowledge_id,
)
from sage_research.infrastructure.json_repository import JsonKnowledgeRepository


def _record(subject: str, claim: str, layer=KnowledgeLayer.MODEL) -> KnowledgeRecord:
    return KnowledgeRecord(
        knowledge_id=stable_knowledge_id(subject, claim),
        layer=layer,
        subject=subject,
        claim=claim,
        state=KnowledgeState.CONFIRMED,
        uncertainty=UncertaintyProfile(
            {
                UncertaintyDomain.MODEL: Confidence(1.0),
                UncertaintyDomain.METHOD: Confidence(0.95),
            }
        ),
        confidence=Confidence(0.95),
        replication=ReplicationStatus.SINGLE_OBSERVATION,
        generalization=GeneralizationState.THIS_SPECIMEN,
        evidence=(
            EvidenceRef(
                source_kind="architecture_inspection",
                source_id="rpt-0",
                category=EvidenceCategory.ARCHITECTURE,
                strength=EvidenceStrength.CONFIRMED,
                description="test",
                timestamp_utc="2026-01-01T00:00:00+00:00",
            ),
        ),
        counterevidence=(),
        dependencies=(),
        system_version="0.0.0-test",
        created_utc="2026-01-01T00:00:00+00:00",
        provenance="unit_test",
    )


def test_save_get_round_trip(tmp_path):
    repo = JsonKnowledgeRepository(tmp_path / "knowledge")
    record = _record("pythia/pythia-70m@default", "hidden_size == 512")
    repo.save(record)

    loaded = repo.get(record.knowledge_id)
    assert loaded == record


def test_all_records_sorted_and_found(tmp_path):
    repo = JsonKnowledgeRepository(tmp_path / "knowledge")
    a = _record("s1", "claim a")
    b = _record("s2", "claim b")
    repo.save(b)
    repo.save(a)

    all_records = repo.all_records()
    assert [r.knowledge_id for r in all_records] == sorted([a.knowledge_id, b.knowledge_id])

    found = repo.find(subject="s2")
    assert len(found) == 1
    assert found[0].subject == "s2"


def test_get_missing_returns_none(tmp_path):
    repo = JsonKnowledgeRepository(tmp_path / "knowledge")
    assert repo.get("kn-does-not-exist") is None


def test_save_is_idempotent(tmp_path):
    repo = JsonKnowledgeRepository(tmp_path / "knowledge")
    record = _record("s", "claim")
    repo.save(record)
    repo.save(record)
    assert len(repo.all_records()) == 1
