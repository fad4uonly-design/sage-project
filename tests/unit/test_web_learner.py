"""Unit tests for the WebLearner RAG-to-memory pipeline.

No network access anywhere: the searcher and summarizer are fake async
callables, and the memory double (or the real SQLite stack with the offline
hashing embeddings) covers both pure logic and real persistence.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sage.config.settings import Settings
from sage.core.web_learner import (
    WebLearnedMemory,
    WebLearner,
    WebLearnError,
    WebResult,
)
from sage.db.connection import Database
from sage.db.migrations import apply_migrations
from sage.events.bus import InMemoryEventBus
from sage.memory.cognitive import CognitiveMemorySupport
from sage.memory.index import SqliteVectorIndex
from sage.memory.memory_interface import MemoryHit
from sage.memory.models import MemoryType
from sage.memory.service import SQLiteMemorySystem
from sage.memory.store import MemoryStore
from sage.models.local_embedding import HashingEmbeddingModel

TOPIC = "what is rust programming"
SUMMARY = "Rust is memory-safe."

RESULTS = [
    WebResult(source="https://rust-lang.org", content="Rust is a systems programming language."),
    WebResult(source="https://wiki.example/rust", content="Rust emphasizes memory safety."),
    WebResult(source="https://blog.example/rust", content="Rust has no garbage collector."),
]


class RecordingMemory:
    """Duck-typed MemoryInterface double recording writes (pure-logic tests)."""

    def __init__(self, known: MemoryHit | None = None) -> None:
        self.known = known
        self.writes: list[tuple[str, str]] = []

    async def has_similar(self, request_text: str) -> bool:
        return self.known is not None

    async def lookup(self, request_text: str) -> MemoryHit | None:
        return self.known

    async def write(self, request_text: str, value: str) -> None:
        self.writes.append((request_text, value))


class FakeSearcher:
    def __init__(self, results: Sequence[WebResult]) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    async def __call__(self, topic: str) -> list[WebResult]:
        self.calls.append(topic)
        return list(self.results)


class FakeSummarizer:
    def __init__(self, summary: str) -> None:
        self.summary = summary
        self.seen: list[tuple[str, list[WebResult]]] = []

    async def __call__(self, topic: str, results: Sequence[WebResult]) -> str:
        self.seen.append((topic, list(results)))
        return self.summary


def make_learner(
    memory: RecordingMemory,
    *,
    results: Sequence[WebResult] | None = None,
    summary: str = SUMMARY,
    max_results: int = 5,
) -> tuple[WebLearner, FakeSearcher, FakeSummarizer]:
    searcher = FakeSearcher(RESULTS if results is None else results)
    summarizer = FakeSummarizer(summary)
    learner = WebLearner(memory, searcher, summarizer, max_results=max_results)
    return learner, searcher, summarizer


async def test_learn_serves_existing_memory_without_searching() -> None:
    memory = RecordingMemory(
        known=MemoryHit(key="mem_123", value="Rust, from memory.", confidence=0.9, age_seconds=5.0)
    )
    learner, searcher, _summarizer = make_learner(memory)

    out = await learner.learn(TOPIC)

    assert out.topic == TOPIC
    assert out.summary == "Rust, from memory."
    assert out.sources == ["memory:mem_123"]
    assert out.learned_at.tzinfo is not None
    assert searcher.calls == []  # did not search the web
    assert memory.writes == []  # did not relearn / rewrite


async def test_learn_searches_summarizes_and_writes() -> None:
    memory = RecordingMemory()
    learner, searcher, summarizer = make_learner(memory)

    out = await learner.learn(TOPIC)

    assert out.summary == SUMMARY
    assert out.sources == [r.source for r in RESULTS]
    assert out.learned_at.tzinfo is not None
    assert searcher.calls == [TOPIC]
    assert summarizer.seen[0][0] == TOPIC
    assert memory.writes == [(TOPIC, SUMMARY)]


async def test_learn_caps_results_handed_to_summarizer() -> None:
    memory = RecordingMemory()
    learner, _searcher, summarizer = make_learner(memory, max_results=2)

    out = await learner.learn(TOPIC)

    assert out.sources == [RESULTS[0].source, RESULTS[1].source]
    assert [r.source for r in summarizer.seen[0][1]] == [RESULTS[0].source, RESULTS[1].source]


async def test_learn_dedupes_sources_and_skips_empty_content() -> None:
    memory = RecordingMemory()
    results = [
        RESULTS[0],
        WebResult(source=RESULTS[0].source, content="duplicate source"),
        WebResult(source="empty.example", content="   "),
        RESULTS[2],
    ]
    learner, _searcher, summarizer = make_learner(memory, results=results)

    out = await learner.learn(TOPIC)

    assert out.sources == [RESULTS[0].source, RESULTS[2].source]
    assert [r.source for r in summarizer.seen[0][1]] == out.sources


async def test_learn_raises_when_no_usable_results() -> None:
    memory = RecordingMemory()
    learner, _searcher, _summarizer = make_learner(memory, results=[])

    try:
        await learner.learn(TOPIC)
    except WebLearnError:
        pass
    else:
        raise AssertionError("expected WebLearnError for zero results")
    assert memory.writes == []  # failures leave no memory trace


async def test_learn_raises_when_all_results_empty() -> None:
    memory = RecordingMemory()
    learner, _searcher, _summarizer = make_learner(
        memory, results=[WebResult(source="x.example", content="   ")]
    )

    try:
        await learner.learn(TOPIC)
    except WebLearnError:
        pass
    else:
        raise AssertionError("expected WebLearnError for all-empty results")
    assert memory.writes == []


async def test_learn_raises_on_empty_summary() -> None:
    memory = RecordingMemory()
    learner, _searcher, _summarizer = make_learner(memory, summary="   ")

    try:
        await learner.learn(TOPIC)
    except WebLearnError:
        pass
    else:
        raise AssertionError("expected WebLearnError for empty summary")
    assert memory.writes == []


async def test_learn_rejects_blank_topic() -> None:
    memory = RecordingMemory()
    learner, searcher, _summarizer = make_learner(memory)

    try:
        await learner.learn("   ")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for blank topic")
    assert searcher.calls == []


# -- Integration: real memory stack, still zero network -----------------------


def make_settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        env="test",
        data_dir=data,
        db_path=data / "web_learner.db",
        logging={"level": "WARNING", "format": "console"},
        scheduler={"enabled": False},
        plugins={"enabled": False, "auto_load": False},
    )


async def make_web_learned_memory(
    tmp_path: Path,
) -> tuple[WebLearnedMemory, SQLiteMemorySystem, Database]:
    settings = make_settings(tmp_path)
    db = Database(settings.db_path)
    await db.open()
    await apply_migrations(db)

    cognitive = CognitiveMemorySupport(db)
    await cognitive.ensure_content_hash_column()
    index = SqliteVectorIndex(db)
    await index.ensure_table()
    index.attach(HashingEmbeddingModel(dim=128))

    system = SQLiteMemorySystem(
        MemoryStore(db), cognitive, InMemoryEventBus(), settings, index=index
    )
    return WebLearnedMemory(system, index), system, db


async def test_end_to_end_learn_then_relearn_from_real_memory(tmp_path: Path) -> None:
    memory, system, db = await make_web_learned_memory(tmp_path)
    try:
        learner, searcher, _summarizer = make_learner(memory)

        first = await learner.learn(TOPIC)
        assert first.summary == SUMMARY
        assert first.sources == [r.source for r in RESULTS]

        # (d) Tagged as self-learned inside the REAL memory system.
        items = await system.recall("rust programming")
        assert items, "learned summary must live in the real memory system"
        stored = items[0]
        assert stored.source == "web_learned"
        assert stored.metadata["via"] == "web_learner"
        assert stored.metadata["learned_from"] == "web"
        assert stored.type == MemoryType.SEMANTIC
        assert stored.summary == SUMMARY

        # (a) Second learn of the same topic: served from memory, no re-search,
        # and no duplicate item written.
        second = await learner.learn(TOPIC)
        assert second.summary == SUMMARY
        assert second.sources[0].startswith("memory:")
        assert searcher.calls == [TOPIC]
        assert await system.count() == 1
    finally:
        await db.close()

