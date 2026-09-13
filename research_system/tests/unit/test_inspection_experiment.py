from __future__ import annotations

from sage_research.domain.architecture_map import ComponentKind
from sage_research.domain.knowledge import KnowledgeLayer, KnowledgeState
from sage_research.domain.model_artifact import ModelArtifact
from sage_research.experiments.architecture_inspector import HeuristicArchitectureInspector
from sage_research.experiments.inspection import ModelInspectionExperiment
from sage_research.infrastructure.in_memory_repository import InMemoryKnowledgeRepository

from ..helpers import (
    EXPECTED_NUM_COMPONENTS,
    EXPECTED_NUM_CONNECTIONS,
    EXPECTED_NUM_RECORDS,
    EXPECTED_TOTAL_PARAMETERS,
    FakeLoadedModel,
)

FIXED_NOW = "2026-08-13T12:00:00+00:00"


def _make_experiment(repository=None, clock=None):
    return ModelInspectionExperiment(
        loader=_FakeLoader(),
        inspector=HeuristicArchitectureInspector(),
        repository=repository or InMemoryKnowledgeRepository(),
        system_version="0.0.0-test",
        clock=clock or (lambda: FIXED_NOW),
    )


class _FakeLoader:
    def load(self, artifact, options=None):
        return FakeLoadedModel(identity=artifact.to_identity())


def test_inspection_map_summary():
    report = _make_experiment().run(ModelArtifact(name="fake-16m", family="fake"))
    amap = report.architecture_map
    assert amap.model_identity.name == "fake-16m"
    assert amap.summary.total_parameters == EXPECTED_TOTAL_PARAMETERS
    assert amap.summary.num_layers == 2
    assert amap.summary.hidden_size == 16
    assert amap.summary.vocab_size == 64
    assert amap.summary.num_attention_heads == 2
    assert amap.summary.intermediate_size == 32
    assert amap.summary.architecture_label == "fake_gpt_neox"
    assert amap.summary.head_dim == 8


def test_inspection_map_components_and_connections():
    report = _make_experiment().run(ModelArtifact(name="fake-16m", family="fake"))
    amap = report.architecture_map
    assert len(amap.components) == EXPECTED_NUM_COMPONENTS
    kinds = {c.kind for c in amap.components}
    assert ComponentKind.EMBEDDING in kinds
    assert ComponentKind.ATTENTION in kinds
    assert ComponentKind.FEEDFORWARD in kinds
    assert ComponentKind.NORMALIZATION in kinds
    assert ComponentKind.OUTPUT_HEAD in kinds
    assert len(amap.components_by_kind(ComponentKind.BLOCK)) == 2
    assert len(amap.connections) == EXPECTED_NUM_CONNECTIONS
    assert len(amap.orphan_connections()) == 0


def test_knowledge_records_are_valid():
    report = _make_experiment().run(ModelArtifact(name="fake-16m", family="fake"))
    records = report.knowledge_records
    assert len(records) == EXPECTED_NUM_RECORDS

    for record in records:
        assert record.layer == KnowledgeLayer.MODEL
        assert record.state == KnowledgeState.CONFIRMED
        assert record.confidence.value <= record.confidence_ceiling.value
        assert record.evidence, "confirmed records require evidence"

    claims = " | ".join(r.claim for r in records)
    assert "total_parameters == 6304" in claims
    assert "num_layers == 2" in claims
    assert "hidden_size == 16" in claims
    assert "resolves to" in claims

    # Dependency chain: every non-identity record depends on the identity record.
    identity = records[0]
    assert identity.dependencies == ()
    for record in records[1:]:
        assert record.dependencies and record.dependencies[0].knowledge_id == identity.knowledge_id


def test_run_is_deterministic_given_fixed_clock():
    repo = InMemoryKnowledgeRepository()
    experiment = _make_experiment(repository=repo)
    first = experiment.run(ModelArtifact(name="fake-16m", family="fake"))
    second = experiment.run(ModelArtifact(name="fake-16m", family="fake"))
    assert first.report_id == second.report_id
    assert [r.knowledge_id for r in first.knowledge_records] == [
        r.knowledge_id for r in second.knowledge_records
    ]


def test_records_persisted_to_repository():
    repo = InMemoryKnowledgeRepository()
    report = _make_experiment(repository=repo).run(ModelArtifact(name="fake-16m", family="fake"))
    assert len(repo.all_records()) == len(report.knowledge_records)
    assert repo.get(report.knowledge_records[0].knowledge_id) == report.knowledge_records[0]


def test_report_carries_environment_and_rerun_config():
    report = _make_experiment().run(
        ModelArtifact(name="fake-16m", family="fake"),
        rerun_configuration={"model": "fake-16m"},
    )
    assert report.environment.system_version == "0.0.0-test"
    assert report.rerun_configuration["model"] == "fake-16m"
    assert report.started_utc == FIXED_NOW
    assert report.completed_utc == FIXED_NOW
