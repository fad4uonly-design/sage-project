"""Integration: GPT-2 Small through the TinyStories bench.

Requires the ``pytorch`` extra and network access to download
``openai-community/gpt2``. Skips cleanly when either is unavailable, so the
unit suite never depends on this. Run with::

    pytest -m integration
"""

from __future__ import annotations

import pytest

pytest.importorskip("torch")
pytest.importorskip("transformers")

from sage_research.domain.model_registry import get_model  # noqa: E402
from sage_research.experiments.model_bench import (  # noqa: E402
    ModelBenchExperiment,
    TinyStoriesSuite,
)
from sage_research.infrastructure.pytorch_generative import (  # noqa: E402
    PyTorchGenerativeLoader,
)

MODEL_KEY = "gpt2-small"


@pytest.fixture(scope="module")
def handle():
    from sage_research.domain.model_artifact import ModelArtifact

    model = get_model(MODEL_KEY)
    loader = PyTorchGenerativeLoader()
    artifact = ModelArtifact(
        name=model.key,
        family=model.family,
        source=f"huggingface:{model.hf_candidates[0]}",
    )
    try:
        return loader.load(artifact)
    except Exception as exc:  # network / disk / permission issues
        pytest.skip(f"{MODEL_KEY} could not be loaded: {exc!r}")


@pytest.mark.integration
def test_gpt2_small_generates_prose(handle) -> None:  # noqa: ANN001
    continuation = handle.generate(
        "Once upon a time, there was a little girl named Lily. She",
        max_new_tokens=24,
    )
    assert isinstance(continuation, str)
    assert len(continuation.split()) >= 1


@pytest.mark.integration
def test_gpt2_small_bench_scores_in_range(handle) -> None:  # noqa: ANN001
    experiment = ModelBenchExperiment(loader=PyTorchGenerativeLoader())
    model = get_model(MODEL_KEY)
    result = experiment.run(model, TinyStoriesSuite.builtin(), handle)
    assert 0.0 <= result.mean_score <= 100.0
    assert len(result.per_case) == len(TinyStoriesSuite.builtin().cases)
