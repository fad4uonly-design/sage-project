"""Model bench — cheap, deterministic evaluation across the model registry.

The bench answers one question for the SOUP/Evolver loop: *is this model
variant actually better on a cheap, reproducible eval set?* It deliberately
does NOT attempt a leaderboard benchmark. The built-in suite is a TinyStories-
style smoke evaluation: short prompts, generated continuations, and a
transparent score made of length sanity, repetition, and (optionally) keyword
coverage of an expected continuation.

Everything runs through the injected :class:`GenerativeModelHandle` port, so
the experiment is runtime-agnostic and unit-testable with fake handles.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..domain.knowledge import utcnow_iso
from ..domain.model_artifact import ModelArtifact
from ..domain.model_registry import BenchModel
from ..interfaces.generative import GenerativeModelHandle

_STOP = frozenset(
    "a an the and or but if in on at to for of is are was were be been it its "
    "i me my we our you your they them their with from as by".split()
)


def _keywords(text: str) -> list[str]:
    tokens = []
    for raw in text.lower().split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if len(token) >= 3 and token not in _STOP:
            tokens.append(token)
    return tokens


@dataclass(frozen=True)
class TinyStoriesCase:
    """One smoke-eval prompt; ``expected`` is optional reference prose."""

    id: str
    prompt: str
    expected: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"id": self.id, "prompt": self.prompt, "expected": self.expected}


@dataclass(frozen=True)
class TinyStoriesSuite:
    """A TinyStories-style smoke eval set."""

    name: str
    cases: tuple[TinyStoriesCase, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "cases": [c.to_dict() for c in self.cases],
        }

    @classmethod
    def builtin(cls) -> "TinyStoriesSuite":
        """Return the deterministic built-in TinyStories-style smoke suite."""
        cases = (
            TinyStoriesCase(id="lily", prompt="Lily found a shiny red ball.", expected="shiny red ball under the tree"),
            TinyStoriesCase(id="ben", prompt="Ben walked to the old tree.", expected="old tree and asked a bee for honey politely"),
            TinyStoriesCase(id="tom", prompt="Tom saw a cat in the garden.", expected="cat sleeping in the garden grass"),
            TinyStoriesCase(id="anna", prompt="Anna found a green flower.", expected="green flower grew and she showed her friends"),
            TinyStoriesCase(id="sun", prompt="The sun was shining when the morning began.", expected="dressed quickly and ran for the school bus"),
        )
        return cls(name="tinystories-builtin", cases=cases)

    @classmethod
    def from_jsonl(cls, path: Path | str) -> "TinyStoriesSuite":
        """Load a user-supplied suite: one JSON object per line.

        Each line: ``{"id": ..., "prompt": ..., "expected": optional}``.
        """
        cases: list[TinyStoriesCase] = []
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                cases.append(
                    TinyStoriesCase(
                        id=str(data["id"]),
                        prompt=str(data["prompt"]),
                        expected=(
                            None
                            if data.get("expected") is None
                            else str(data["expected"])
                        ),
                    )
                )
        if not cases:
            raise ValueError(f"Eval suite file is empty: {path}")
        return cls(name=Path(path).stem, cases=tuple(cases))


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    score: int
    generated: str

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "score": self.score,
            "generated": self.generated,
        }


@dataclass(frozen=True)
class BenchResult:
    """The outcome of one bench run for one registry model."""

    model_key: str
    model_name: str
    suite_name: str
    mean_score: float
    per_case: tuple[CaseScore, ...] = field(default_factory=tuple)
    started_utc: str = ""
    completed_utc: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "model_key": self.model_key,
            "model_name": self.model_name,
            "suite_name": self.suite_name,
            "mean_score": self.mean_score,
            "per_case": [c.to_dict() for c in self.per_case],
            "started_utc": self.started_utc,
            "completed_utc": self.completed_utc,
        }


def _score_generation(generated: str, case: TinyStoriesCase) -> int:
    """Transparent smoke score in 0..100.

    Components (documented, deterministic):
      * presence: 0 for empty output
      * length sanity: 3..120 words is a healthy continuation
      * repetition: distinct-word ratio penalizes degenerate loops
      * coverage: keyword overlap with ``expected`` when provided
    """
    text = generated.strip()
    if not text:
        return 0

    words = text.split()
    lower_words = [w.lower().strip(".,!?;:\"'") for w in words]
    lower_words = [w for w in lower_words if w]

    # Length sanity.
    if len(lower_words) < 3:
        length_score = 0.2
    elif len(lower_words) <= 120:
        length_score = 1.0
    else:
        length_score = 0.6

    # Repetition: ratio of distinct words.
    distinct = len(set(lower_words)) / max(len(lower_words), 1)
    repetition_score = min(1.0, distinct / 0.6)  # 60%+ distinct is fine

    base = 40.0 * length_score + 30.0 * repetition_score

    if case.expected:
        expected_keys = _keywords(case.expected)
        if expected_keys:
            covered = sum(1 for kw in expected_keys if kw in set(lower_words))
            coverage = covered / len(expected_keys)
            base += 30.0 * coverage
        else:
            base += 15.0
    else:
        # No reference: give the remaining weight to a fluency proxy.
        base += 30.0 * min(1.0, len(lower_words) / 20.0)

    return max(0, min(100, round(base)))


class ModelBenchExperiment:
    """Runs one registry model through an eval suite via a loaded handle.

    Args:
        loader: a :class:`~sage_research.interfaces.generative.GenerativeModelLoader`
            (kept untyped to avoid a runtime dependency on any adapter).
        clock: injectable UTC-now callable for deterministic tests.
    """

    def __init__(
        self,
        *,
        loader: object,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._loader = loader
        self._clock = clock or utcnow_iso

    def run(
        self,
        model: BenchModel,
        suite: TinyStoriesSuite,
        handle: GenerativeModelHandle | None = None,
        *,
        artifact: ModelArtifact | None = None,
        max_new_tokens: int = 40,
    ) -> BenchResult:
        """Evaluate ``model``; pass ``handle`` to reuse an already-loaded model.

        When ``handle`` is omitted, ``artifact`` (or a default built from the
        registry row) is loaded through the injected loader.
        """
        started = self._clock()
        if handle is None:
            resolved = artifact or ModelArtifact(
                name=model.key,
                family=model.family,
                source=model.primary_source,
            )
            handle = self._load(resolved)  # type: ignore[assignment]

        per_case: list[CaseScore] = []
        for case in suite.cases:
            generated = handle.generate(
                case.prompt, max_new_tokens=max_new_tokens
            )
            per_case.append(
                CaseScore(
                    case_id=case.id,
                    score=_score_generation(generated, case),
                    generated=generated,
                )
            )

        mean_score = (
            sum(c.score for c in per_case) / len(per_case) if per_case else 0.0
        )
        return BenchResult(
            model_key=model.key,
            model_name=model.name,
            suite_name=suite.name,
            mean_score=round(mean_score, 2),
            per_case=tuple(per_case),
            started_utc=started,
            completed_utc=self._clock(),
        )

    def _load(self, artifact: ModelArtifact):  # noqa: ANN202
        return self._loader.load(artifact)
