"""Integration tests for the Pythia-70M inspection path.

Requires the ``pytorch`` extra (torch + transformers) and network access to
download ``EleutherAI/pythia-70m``. Each test skips cleanly when either is
unavailable, so the unit-test suite never depends on these.

Run with::

    pytest -m integration
"""

from __future__ import annotations

import pytest

pytest.importorskip("torch")
pytest.importorskip("transformers")

from sage_research.domain.architecture_map import ComponentKind  # noqa: E402
from sage_research.domain.knowledge import KnowledgeState  # noqa: E402
from sage_research.domain.model_artifact import ModelArtifact  # noqa: E402
from sage_research.experiments.architecture_inspector import (
    HeuristicArchitectureInspector,  # noqa: E402
)
from sage_research.experiments.inspection import ModelInspectionExperiment  # noqa: E402
from sage_research.infrastructure.in_memory_repository import (
    InMemoryKnowledgeRepository,  # noqa: E402
)
from sage_research.infrastructure.pytorch_loader import PyTorchModelLoader  # noqa: E402

MODEL_SOURCE = "EleutherAI/pythia-70m"

# Reference values for EleutherAI/pythia-70m (GPT-NeoX family).
EXPECTED_LAYERS = 6
EXPECTED_HIDDEN = 512
EXPECTED_VOCAB = 50304
EXPECTED_HEADS = 8
EXPECTED_INTERMEDIATE = 2048
EXPECTED_PARAMS_MIN = 60_000_000
EXPECTED_PARAMS_MAX = 80_000_000


@pytest.fixture(scope="module")
def loaded_model():
    loader = PyTorchModelLoader()
    artifact = ModelArtifact(
        name="pythia-70m",
        family="pythia",
        source=f"huggingface:{MODEL_SOURCE}",
    )
    try:
        return loader.load(artifact)
    except Exception as exc:  # network / disk / permission issues
        pytest.skip(f"pythia-70m could not be loaded: {exc!r}")


@pytest.fixture(scope="module")
def architecture_map(loaded_model):
    return HeuristicArchitectureInspector().inspect(loaded_model)


@pytest.mark.integration
def test_pythia70m_summary(architecture_map):
    s = architecture_map.summary
    assert s.architecture_label == "gpt_neox"
    assert s.num_layers == EXPECTED_LAYERS
    assert s.hidden_size == EXPECTED_HIDDEN
    assert s.vocab_size == EXPECTED_VOCAB
    assert s.num_attention_heads == EXPECTED_HEADS
    assert s.intermediate_size == EXPECTED_INTERMEDIATE
    assert EXPECTED_PARAMS_MIN < s.total_parameters < EXPECTED_PARAMS_MAX
    assert s.total_parameters == s.trainable_parameters


@pytest.mark.integration
def test_pythia70m_components_and_connections(architecture_map):
    kinds = {c.kind for c in architecture_map.components}
    for expected in (
        ComponentKind.EMBEDDING,
        ComponentKind.ATTENTION,
        ComponentKind.FEEDFORWARD,
        ComponentKind.NORMALIZATION,
        ComponentKind.OUTPUT_HEAD,
        ComponentKind.BLOCK,
    ):
        assert expected in kinds, f"missing component kind {expected}"

    blocks = architecture_map.components_by_kind(ComponentKind.BLOCK)
    assert len(blocks) == EXPECTED_LAYERS
    assert len(architecture_map.components) > 10
    assert len(architecture_map.connections) > 0
    assert len(architecture_map.orphan_connections()) == 0


@pytest.mark.integration
def test_pythia70m_full_experiment(loaded_model):
    repository = InMemoryKnowledgeRepository()
    experiment = ModelInspectionExperiment(
        loader=_PreloadedLoader(loaded_model),
        inspector=HeuristicArchitectureInspector(),
        repository=repository,
    )
    report = experiment.run(
        ModelArtifact(name="pythia-70m", family="pythia", source=f"huggingface:{MODEL_SOURCE}")
    )

    assert report.identity.name == "pythia-70m"
    assert len(report.knowledge_records) > 10
    for record in report.knowledge_records:
        assert record.state == KnowledgeState.CONFIRMED
        assert record.confidence.value <= record.confidence_ceiling.value

    claims = " | ".join(r.claim for r in report.knowledge_records)
    assert "total_parameters ==" in claims
    assert f"num_layers == {EXPECTED_LAYERS}" in claims
    assert f"hidden_size == {EXPECTED_HIDDEN}" in claims

    # Every record persisted.
    assert len(report.knowledge_records) == len(repository.all_records())


class _PreloadedLoader:
    """Reuses the already-downloaded model to avoid a second network load."""

    def __init__(self, loaded_model):
        self._loaded = loaded_model

    def load(self, artifact, options=None):
        return self._loaded
