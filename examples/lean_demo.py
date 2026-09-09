"""
Lean Intelligence demo: routes a handful of requests through ValueRouter +
LeanLoop on top of SAGE's REAL memory system (SQLiteMemorySystem +
SqliteVectorIndex with the offline HashingEmbeddingModel).

Run from repo root after `pip install -e .`:

    python examples/lean_demo.py

Watch the second "capital of France" request: the first turn executed the
executor and wrote the answer to real memory; the second turn short-circuits
(MEMORY_ONLY) without calling the executor again. The canned answers are
kept deliberately short — long cached values dilute exact-repeat confidence
in the offline hashing space (see sage/memory/memory_interface.py).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sage.config.settings import Settings
from sage.core.lean_loop import LeanLoop
from sage.core.value_router import ValueRouter
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

CANNED_ANSWERS = {
    "What is the capital of France?": "Paris.",
    "Compare the trade-offs of vLLM vs llama.cpp for local inference": (
        "vLLM: faster serving. llama.cpp: lighter setup."
    ),
    "What's the current weather in Kuwait City?": "32C, clear skies (via tool).",
    "Convert 100 fahrenheit to celsius": "About 37.8C.",
}


async def build_loop(data: Path) -> tuple[LeanLoop, Database]:
    settings = Settings(
        env="development",
        data_dir=data,
        db_path=data / "sage.db",
        logging={"level": "WARNING", "format": "console"},  # type: ignore[arg-type]
        scheduler={"enabled": False},  # type: ignore[arg-type]
        plugins={"enabled": False, "auto_load": False},  # type: ignore[arg-type]
    )
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
    memory = MemoryInterface(system, index)

    # Hashing-space exact repeats land ~0.87; the 0.9 MEMORY_ONLY gate is
    # calibrated for real embedding spaces, so lower it for this demo.
    router = ValueRouter(memory=memory, memory_only_confidence=0.85)
    return LeanLoop(router=router), db


async def executor(request_text: str, model: ModelCard | None, use_tools: bool) -> str:
    """Stand-in for SAGE's real reasoning/agent pipeline.

    Returns the bare answer — routing metadata belongs to the TaskOutcome,
    not to the cached value (short values keep exact-repeat confidence high).
    """
    answer = CANNED_ANSWERS.get(request_text, "A short, verified answer.")
    if use_tools:
        answer = f"{answer} [tools used]"
    return answer


async def main() -> None:
    loop, db = await build_loop(Path("./data/lean_demo"))
    try:
        requests = [
            "What is the capital of France?",  # trivial -> cheap model
            "What is the capital of France?",  # duplicate -> MEMORY_ONLY
            "Compare the trade-offs of vLLM vs llama.cpp for local inference",  # complex
            "What's the current weather in Kuwait City?",  # needs tool
            "Convert 100 fahrenheit to celsius",  # trivial
        ]
        for request in requests:
            outcome = await loop.run(request, executor)
            print("=" * 70)
            print(f"REQUEST : {request}")
            print(f"DECISION: {outcome.decision.value}")
            print(f"MODEL   : {outcome.model_used}")
            print(f"TOOLS   : {outcome.used_tools}")
            print(f"COST    : ${outcome.estimated_cost_usd}")
            print(f"RESULT  : {outcome.result}")
        print("=" * 70)
        print("KAIZEN SUMMARY")
        for key, value in loop.waste_summary().items():
            print(f"{key}: {value}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
