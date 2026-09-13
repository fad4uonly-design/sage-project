"""Tests for the TinyStories model bench (fake handles, no torch)."""

from __future__ import annotations

import json

import pytest

from sage_research.domain.model_registry import get_model
from sage_research.experiments.model_bench import (
    ModelBenchExperiment,
    TinyStoriesCase,
    TinyStoriesSuite,
    _score_generation,
)
from sage_research.domain.model_artifact import ModelArtifact

CLOCK_STEPS = {"n": 0}


def fake_clock() -> str:
    CLOCK_STEPS["n"] += 1
    return f"2026-01-01T00:00:{CLOCK_STEPS['n']:02d}Z"


class FakeHandle:
    """Deterministic handle: echoes a canned continuation per prompt token."""

    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses

    @property
    def identity(self):  # noqa: ANN201 - duck-typed port
        raise AssertionError("not used in this test")

    def generate(self, prompt: str, *, max_new_tokens: int = 40) -> str:
        for key, value in self._responses.items():
            if key in prompt:
                return value
        return ""


class FakeLoader:
    """Loader returning a fixed handle; records loaded sources."""

    def __init__(self, handle: FakeHandle) -> None:
        self.handle = handle
        self.loaded: list[str] = []

    def load(self, artifact, options=None):  # noqa: ANN001, ANN201
        self.loaded.append(artifact.source)
        return self.handle


@pytest.fixture()
def suite() -> TinyStoriesSuite:
    return TinyStoriesSuite.builtin()


def test_builtin_suite_has_cases() -> None:
    suite = TinyStoriesSuite.builtin()
    assert suite.name == "tinystories-builtin"
    assert len(suite.cases) >= 5
    assert all(case.prompt for case in suite.cases)


def test_empty_generation_scores_zero() -> None:
    case = TinyStoriesCase(id="c", prompt="p")
    assert _score_generation("", case) == 0
    assert _score_generation("   ", case) == 0


def test_good_continuation_scores_higher_than_degenerate() -> None:
    case = TinyStoriesCase(
        id="c",
        prompt="p",
        expected="the small red ball under the tree",
    )
    good = "She found the small red ball under the old tree and smiled."
    degenerate = "the the the the the the the the the the"
    assert _score_generation(good, case) > _score_generation(degenerate, case)


def test_bench_runs_all_cases_and_reports_mean(suite: TinyStoriesSuite) -> None:
    handle = FakeHandle(
        {
            "Lily": "a shiny red ball under the tree and she was happy",
            "Ben": "the old tree and asked a bee for honey politely",
            "Tom": "a cat sleeping in the garden grass",
            "Anna": "a green flower grew and she showed her friends",
            "The sun": "dressed quickly and ran for the school bus",
        }
    )
    experiment = ModelBenchExperiment(loader=FakeLoader(handle), clock=fake_clock)
    model = get_model("pythia-70m")
    result = experiment.run(model, suite, handle)

    assert len(result.per_case) == len(suite.cases)
    assert 0.0 <= result.mean_score <= 100.0
    assert result.model_key == "pythia-70m"
    payload = result.to_dict()
    assert payload["suite_name"] == suite.name


def test_bench_loads_through_loader_when_no_handle(suite: TinyStoriesSuite) -> None:
    handle = FakeHandle({"Lily": "a red ball"})
    loader = FakeLoader(handle)
    experiment = ModelBenchExperiment(loader=loader, clock=fake_clock)
    model = get_model("gpt2-small")
    experiment.run(model, suite, max_new_tokens=5)
    assert loader.loaded == ["huggingface:openai-community/gpt2"]


def test_suite_from_jsonl(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "suite.jsonl"
    rows = [
        {"id": "x1", "prompt": "Once upon a time", "expected": "a small bear"},
        {"id": "x2", "prompt": "The dog ran", "expected": None},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    suite = TinyStoriesSuite.from_jsonl(path)
    assert suite.name == "suite"
    assert [c.id for c in suite.cases] == ["x1", "x2"]
    assert suite.cases[0].expected == "a small bear"
    assert suite.cases[1].expected is None


def test_empty_jsonl_suite_rejected(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        TinyStoriesSuite.from_jsonl(path)
