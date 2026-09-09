"""Unit tests for the Lean Intelligence core: WasteDetector, ModelRegistry,
ValueRouter, and LeanLoop — including end-to-end wiring against the REAL
memory system (SQLiteMemorySystem + SqliteVectorIndex, hashing embeddings).
"""

from __future__ import annotations

from pathlib import Path

from sage.config.settings import Settings
from sage.core.lean_loop import LeanLoop
from sage.core.value_router import RoutingDecision, ValueRouter
from sage.core.waste_detector import Complexity, WasteDetector
from sage.db.connection import Database
from sage.db.migrations import apply_migrations
from sage.events.bus import InMemoryEventBus
from sage.memory.cognitive import CognitiveMemorySupport
from sage.memory.index import SqliteVectorIndex
from sage.memory.memory_interface import MemoryInterface
from sage.memory.service import SQLiteMemorySystem
from sage.memory.store import MemoryStore
from sage.models.local_embedding import HashingEmbeddingModel
from sage.models.model_card import ModelCard
from sage.models.registry import ModelRegistry

QUESTION = "What is the capital of France?"
ANSWER = "Paris."
COMPLEX = "Compare the trade-offs of vLLM vs llama.cpp for local inference"
TOOLISH = "What's the current weather in Kuwait City?"
TRIVIAL_MATH = "Convert 100 fahrenheit to celsius"


def make_settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        env="test",
        data_dir=data,
        db_path=data / "lean_core.db",
        logging={"level": "WARNING", "format": "console"},
        scheduler={"enabled": False},
        plugins={"enabled": False, "auto_load": False},
    )


async def make_stack(
    tmp_path: Path,
) -> tuple[MemoryInterface, SQLiteMemorySystem, Database]:
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
    return MemoryInterface(system, index), system, db


# -- WasteDetector -----------------------------------------------------------


def test_complexity_classification() -> None:
    waste = WasteDetector()
    assert waste.classify_complexity(QUESTION) is Complexity.TRIVIAL
    assert waste.classify_complexity("Tell me about photosynthesis") is Complexity.MODERATE
    assert waste.classify_complexity(COMPLEX) is Complexity.COMPLEX


def test_needs_tool_detection() -> None:
    waste = WasteDetector()
    assert waste.needs_tool(TOOLISH) is True
    assert waste.needs_tool(QUESTION) is False


def test_evaluate_flags_duplicates_and_skill_extraction() -> None:
    waste = WasteDetector()
    assert waste.evaluate(QUESTION).duplicate_of_recent is False
    assert waste.evaluate(QUESTION).duplicate_of_recent is True
    waste.evaluate(QUESTION)  # third sighting
    assert waste.evaluate(QUESTION).recommend_skill_extraction is True


def test_record_failure_marks_rework() -> None:
    waste = WasteDetector()
    waste.record_failure(QUESTION)
    assert waste.evaluate(QUESTION).previously_failed is True


# -- ModelRegistry -----------------------------------------------------------


def test_cheapest_sufficient_default_is_tiny_local() -> None:
    model = ModelRegistry().cheapest_sufficient()
    assert model is not None
    assert model.identity.name == "Qwen2.5-1.5B-Instruct"


def test_needs_tools_skips_prompted_only_models() -> None:
    model = ModelRegistry().cheapest_sufficient(needs_tools=True)
    assert model is not None
    assert model.tool_use.value == "native"
    assert model.identity.name == "Qwen2.5-14B-Instruct"


def test_long_context_picks_mid_local() -> None:
    model = ModelRegistry().cheapest_sufficient(needs_long_context_tokens=100_000)
    assert model is not None
    assert model.identity.name == "Qwen2.5-14B-Instruct"


def test_needs_vision_picks_frontier() -> None:
    model = ModelRegistry().cheapest_sufficient(needs_vision=True)
    assert model is not None
    assert model.capabilities.vision is True
    assert model.identity.name == "Claude Sonnet 5"


# -- ValueRouter (against the real memory stack) ------------------------------


async def test_router_without_memory_still_routes(tmp_path: Path) -> None:
    router = ValueRouter()  # no memory wired: pure complexity/tool routing
    plan = await router.route(QUESTION)
    assert plan.decision is RoutingDecision.CHEAP_MODEL
    assert plan.memory_hit is None
    assert plan.model is not None


async def test_high_confidence_hit_routes_memory_only(tmp_path: Path) -> None:
    iface, _system, db = await make_stack(tmp_path)
    try:
        # Hashing-space exact repeats land ~0.87, so lower the gate (0.9 is
        # calibrated for real embedding spaces — see memory_interface docs).
        router = ValueRouter(memory=iface, memory_only_confidence=0.85)
        await iface.write(QUESTION, ANSWER)

        plan = await router.route(QUESTION)

        assert plan.decision is RoutingDecision.MEMORY_ONLY
        assert plan.model is None
        assert plan.memory_hit is not None
        assert plan.memory_hit.value == ANSWER
    finally:
        await db.close()


async def test_hit_below_gate_surfaces_context_without_short_circuit(tmp_path: Path) -> None:
    iface, _system, db = await make_stack(tmp_path)
    try:
        router = ValueRouter(memory=iface)  # default 0.9 gate
        await iface.write(QUESTION, ANSWER)

        plan = await router.route(QUESTION)

        assert plan.decision is RoutingDecision.CHEAP_MODEL
        assert plan.memory_hit is not None, "hit must still surface as context"
        assert plan.model is not None
    finally:
        await db.close()


async def test_complex_request_routes_full_pipeline(tmp_path: Path) -> None:
    iface, _system, db = await make_stack(tmp_path)
    try:
        router = ValueRouter(memory=iface)
        plan = await router.route(COMPLEX)
        assert plan.decision is RoutingDecision.FULL_PIPELINE
        assert plan.model is not None
        assert plan.model.identity.name == "Qwen2.5-14B-Instruct"
    finally:
        await db.close()


async def test_tool_request_routes_full_pipeline_with_tools(tmp_path: Path) -> None:
    iface, _system, db = await make_stack(tmp_path)
    try:
        router = ValueRouter(memory=iface)
        plan = await router.route(TOOLISH)
        assert plan.decision is RoutingDecision.FULL_PIPELINE
        assert plan.use_tools is True
    finally:
        await db.close()


async def test_trivial_request_routes_cheap_model(tmp_path: Path) -> None:
    iface, _system, db = await make_stack(tmp_path)
    try:
        router = ValueRouter(memory=iface)
        plan = await router.route(TRIVIAL_MATH)
        assert plan.decision is RoutingDecision.CHEAP_MODEL
        assert plan.model is not None
        assert plan.model.identity.name == "Qwen2.5-1.5B-Instruct"
    finally:
        await db.close()


# -- LeanLoop end-to-end ------------------------------------------------------


async def test_lean_loop_end_to_end_with_real_memory(tmp_path: Path) -> None:
    iface, system, db = await make_stack(tmp_path)
    try:
        calls: list[str] = []

        async def executor(
            request_text: str, model: ModelCard | None, use_tools: bool
        ) -> str:
            calls.append(request_text)
            return f"answer to: {request_text}"

        # 0.85 gate: hashing-space exact repeats land ~0.87 (see adapter docs).
        loop = LeanLoop(router=ValueRouter(memory=iface, memory_only_confidence=0.85))

        first = await loop.run(QUESTION, executor)
        assert first.decision is RoutingDecision.CHEAP_MODEL
        assert calls == [QUESTION]
        assert first.verified is True
        assert first.estimated_cost_usd == 0.0  # local model

        second = await loop.run(QUESTION, executor)
        assert second.decision is RoutingDecision.MEMORY_ONLY
        assert second.model_used is None
        assert second.result == f"answer to: {QUESTION}"
        assert calls == [QUESTION], "memory short-circuit must not call the executor"

        # Kaizen: the verified result was written to the REAL memory system.
        assert await system.count() == 1

        summary = loop.waste_summary()
        assert summary["total_tasks"] == 2
        assert summary["answered_from_memory_pct"] == 50.0
        assert summary["verification_failures"] == 0
    finally:
        await db.close()


async def test_failed_verification_is_not_written_to_memory(tmp_path: Path) -> None:
    iface, system, db = await make_stack(tmp_path)
    try:

        async def executor(
            request_text: str, model: ModelCard | None, use_tools: bool
        ) -> str:
            return ""  # fails the non-empty verifier

        loop = LeanLoop(router=ValueRouter(memory=iface))
        outcome = await loop.run(TRIVIAL_MATH, executor)

        assert outcome.verified is False
        assert await system.count() == 0, "unverified results must not be cached"
        assert loop.router.waste.failed_before(TRIVIAL_MATH) is True
        assert loop.waste_summary()["verification_failures"] == 1
    finally:
        await db.close()
