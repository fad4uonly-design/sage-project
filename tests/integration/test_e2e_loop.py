"""Integration: full end-to-end SAGE loop (Phase 2).

Every test boots the REAL engine (all modules, real SQLite, real container
wiring) and drives the exact path a user hits:

    ask() → Conversation → Orchestrator (intent → plan → steps)
          → tools / memory / model → response → logging

Deterministic by construction: the language model is a recording fake routed
through the real ModelRouter seam, web search/summarization are fakes behind
the real WebLearner, and embeddings are the offline hashing model. No network,
no Ollama — those are covered by the manual runtime verification.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from sage.api.app import create_app
from sage.audit.logger import AuditLogger
from sage.core.engine import SageEngine
from sage.core.web_learner import WebLearnError, WebLearnedMemory, WebLearner, WebResult
from sage.db.connection import Database
from sage.memory.index import VectorIndex
from sage.memory.service import SQLiteMemorySystem
from sage.models.interfaces import (
    CompletionRequest,
    CompletionResponse,
    EmbeddingModel,
    LanguageModel,
    ModelRouter,
)
from sage.models.local_embedding import HashingEmbeddingModel
from sage.orchestrator.interfaces import Orchestrator
from sage.orchestrator.models import IntentKind
from sage.tools.builtin.web_learn_tool import WebLearnTool
from sage.tools.manager import DefaultToolManager

TOPIC = "what is the water cycle"
SUMMARY = "The water cycle moves water between oceans, air, and land."

SEARCH_RESULTS = [
    WebResult(
        source="https://example.com/water",
        content="Water evaporates, condenses, and precipitates.",
    ),
    WebResult(
        source="https://example.com/cycle",
        content="The cycle is driven by the sun.",
    ),
]


class FakeSearcher:
    """SearchFn double: records topics, returns canned results."""

    def __init__(self, results: Sequence[WebResult]) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    async def __call__(self, topic: str) -> list[WebResult]:
        self.calls.append(topic)
        return list(self.results)


class FakeSummarizer:
    """SummarizeFn double: records topics, returns a canned summary."""

    def __init__(self, summary: str) -> None:
        self.summary = summary
        self.calls: list[str] = []

    async def __call__(self, topic: str, results: Sequence[WebResult]) -> str:
        self.calls.append(topic)
        return self.summary


class FailingSearcher:
    """SearchFn double that finds nothing (web down / no results)."""

    async def __call__(self, topic: str) -> list[WebResult]:
        return []


class RecordingLanguageModel:
    """Deterministic echo LM that records every prompt it is given."""

    def __init__(self) -> None:
        self.prompts: list[list[tuple[str, str]]] = []

    @property
    def provider(self) -> str:
        return "recording"

    @property
    def model_name(self) -> str:
        return "recording-v1"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.prompts.append([(m.role, m.content) for m in request.messages])
        last_user = [m.content for m in request.messages if m.role == "user"][-1]
        return CompletionResponse(
            content=f"echo: {last_user}",
            model=self.model_name,
            provider=self.provider,
        )


class RecordingRouter:
    """Duck-typed ModelRouter: recording LM + offline hashing embeddings."""

    def __init__(self, embedding: EmbeddingModel) -> None:
        self._embedding = embedding
        self.lm = RecordingLanguageModel()

    def get_language_model(self, *, capability: str | None = None) -> LanguageModel:
        return self.lm

    def get_embedding_model(self) -> EmbeddingModel:
        return self._embedding


def install_deterministic_models(engine: SageEngine) -> RecordingRouter:
    """Route compose through a recording LM via the real ModelRouter seam."""
    router = RecordingRouter(embedding=HashingEmbeddingModel(dim=128))
    engine.container.register_instance(ModelRouter, router)
    return router


def install_fake_web_learn(
    engine: SageEngine,
    searcher: Any,
    summarizer: Any,
) -> WebLearner:
    """Replace the boot-wired web_learn tool with a deterministic learner.

    Wiring mirrors production (tools/service.py): real SQLiteMemorySystem,
    real container VectorIndex, embedding attached exactly like the module
    does — only the network-facing searcher and the model-backed summarizer
    are fakes.
    """
    system = engine.container.resolve(SQLiteMemorySystem)
    index = engine.container.resolve(VectorIndex)
    # Mirror production wiring (tools/service.py): the embedding comes from the
    # live ModelRouter, which is the model the index is already attached to.
    router = engine.container.resolve(ModelRouter)
    memory = WebLearnedMemory(system, index, embedding=router.get_embedding_model())
    learner = WebLearner(memory, searcher, summarizer)
    manager = engine.container.resolve(DefaultToolManager)
    manager.register(WebLearnTool(learner=learner))
    return learner


async def fetch_all(engine: SageEngine, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    db = engine.container.resolve(Database)
    return await db.fetchall(sql, params)


# -- Scenario A: direct model interaction -------------------------------------


@pytest.mark.asyncio
async def test_direct_model_interaction_does_not_write_memory(engine: SageEngine) -> None:
    install_deterministic_models(engine)
    mem = engine.container.resolve(SQLiteMemorySystem)
    before = await mem.count()

    reply = await engine.ask("What is the capital of France?")

    assert reply.strip(), "the loop must return a non-empty response"
    assert await mem.count() == before, "a chat question must not create memories"


# -- Interaction logging -------------------------------------------------------


@pytest.mark.asyncio
async def test_interaction_logging_records_session_and_turn(engine: SageEngine) -> None:
    install_deterministic_models(engine)

    await engine.ask("What is the capital of France?")

    turns = await fetch_all(
        engine,
        "SELECT user_message, assistant_message, metadata FROM conversation_turns",
    )
    assert turns, "every ask must persist a conversation turn"
    row = turns[-1]
    assert "capital of France" in row["user_message"]
    assert row["assistant_message"].strip()
    meta = json.loads(row["metadata"])
    assert meta["intent"] == "chat"
    assert meta["plan_id"]

    sessions = await fetch_all(engine, "SELECT ended_at FROM conversations")
    assert sessions and all(s["ended_at"] for s in sessions), "ask() closes its session"


# -- Scenario B: memory store → recall ----------------------------------------


@pytest.mark.asyncio
async def test_remember_then_recall_end_to_end(engine: SageEngine) -> None:
    install_deterministic_models(engine)
    mem = engine.container.resolve(SQLiteMemorySystem)
    before = await mem.count()

    reply = await engine.ask("Remember that my test project is called SAGE.")
    assert "remember" in reply.lower() and "SAGE" in reply
    assert await mem.count() == before + 1, "the remembered fact must be stored"

    recalled = await engine.ask("what do you remember about test project")
    assert "SAGE" in recalled, "recall must serve the stored fact back"


@pytest.mark.asyncio
async def test_chat_question_routes_stored_memory_into_model_prompt(
    engine: SageEngine,
) -> None:
    router = install_deterministic_models(engine)

    await engine.ask("Remember that my test project is called SAGE.")
    await engine.ask("What is my test project called?")

    assert router.lm.prompts, "compose must call the language model"
    system_text = "\n".join(
        content for role, content in router.lm.prompts[-1] if role == "system"
    )
    assert "test project is called SAGE" in system_text, (
        "retrieval must surface the stored fact as model context"
    )

    # Structured retrieval provenance must also survive end-to-end: the
    # orchestrator exposes it in result metadata, the conversation layer
    # persists it on the turn, and it round-trips through the database.
    latest = (
        await fetch_all(
            engine,
            "SELECT metadata FROM conversation_turns ORDER BY rowid DESC LIMIT 1",
        )
    )[-1]
    meta = json.loads(latest["metadata"])
    provenance = meta.get("evidence_provenance")
    assert provenance, "turn metadata must carry non-empty evidence_provenance"
    memory_items = [p for p in provenance if p.get("layer") == "memory"]
    assert memory_items, "provenance must include a memory-layer item"
    assert memory_items[0].get("source_ref"), "memory provenance must cite its source"
    assert "score" not in memory_items[0], (
        "raw retrieval score must not leak into metadata"
    )


# -- Scenario C: operational web learning -------------------------------------


@pytest.mark.asyncio
async def test_web_learn_end_to_end_stores_into_memory(engine: SageEngine) -> None:
    searcher = FakeSearcher(SEARCH_RESULTS)
    summarizer = FakeSummarizer(SUMMARY)
    install_fake_web_learn(engine, searcher, summarizer)
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]

    result = await orch.handle(f"Learn about {TOPIC}")

    assert result.intent.kind == IntentKind.TOOL
    assert SUMMARY in result.response
    assert "example.com" in result.response
    assert searcher.calls == [TOPIC]
    assert summarizer.calls == [TOPIC]

    # The learned content lives in the real memory system, tagged self-learned.
    mem = engine.container.resolve(SQLiteMemorySystem)
    items = await mem.recall(TOPIC)
    assert any(i.source == "web_learned" for i in items)

    # The tool run is audited.
    audit = engine.container.resolve(AuditLogger)
    records = await audit.list_recent(kind="tool", limit=10)
    assert any(r.tool_name == "web_learn" and r.status == "ok" for r in records)


@pytest.mark.asyncio
async def test_repeated_learn_is_served_from_memory(engine: SageEngine) -> None:
    searcher = FakeSearcher(SEARCH_RESULTS)
    summarizer = FakeSummarizer(SUMMARY)
    install_fake_web_learn(engine, searcher, summarizer)
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    mem = engine.container.resolve(SQLiteMemorySystem)

    await orch.handle(f"Learn about {TOPIC}")
    again = await orch.handle(f"Learn about {TOPIC}")

    assert SUMMARY in again.response
    assert "memory:" in again.response, "sources must show the memory serve path"
    assert searcher.calls == [TOPIC], "the second learn must not re-search the web"
    assert await mem.count() == 1, "memory-first must not duplicate stored knowledge"


# -- Scenario D: tool failure / degraded behavior ------------------------------


@pytest.mark.asyncio
async def test_failed_learn_degrades_gracefully_and_audits(engine: SageEngine) -> None:
    install_fake_web_learn(engine, FailingSearcher(), FakeSummarizer(SUMMARY))
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    mem = engine.container.resolve(SQLiteMemorySystem)

    result = await orch.handle(f"Learn about {TOPIC}")

    assert result.intent.kind == IntentKind.TOOL
    assert "couldn't complete" in result.response
    assert "no usable search results" in result.response
    assert await mem.count() == 0, "a failed learn leaves no trace in memory"

    audit = engine.container.resolve(AuditLogger)
    records = await audit.list_recent(kind="tool", limit=10)
    assert any(r.tool_name == "web_learn" and r.status == "error" for r in records)

    # The loop stays healthy: a normal request still completes afterwards.
    assert (await engine.ask("hello there")).strip()


@pytest.mark.asyncio
async def test_weblearn_error_from_summarizer_is_controlled(engine: SageEngine) -> None:
    class BlockedSummarizer:
        async def __call__(self, topic: str, results: Sequence[WebResult]) -> str:
            raise WebLearnError("no live model endpoint configured")

    install_fake_web_learn(engine, FakeSearcher(SEARCH_RESULTS), BlockedSummarizer())
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]

    result = await orch.handle(f"Learn about {TOPIC}")

    assert "couldn't complete" in result.response
    assert "no live model endpoint" in result.response


# -- Interface entry: REST API -------------------------------------------------


@pytest.mark.asyncio
async def test_api_ask_endpoint_memory_loop(engine: SageEngine) -> None:
    install_deterministic_models(engine)
    app = create_app(engine)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post(
            "/api/v1/ask", json={"message": "Remember that my test project is called SAGE."}
        )
        assert r1.status_code == 200
        assert "remember" in r1.json()["reply"].lower()

        r2 = await client.post(
            "/api/v1/ask", json={"message": "what do you remember about test project"}
        )
        assert r2.status_code == 200
        assert "SAGE" in r2.json()["reply"]

