"""
Minimal programmatic use of SAGE.

Run from repo root after `pip install -e .`:

    python examples/quickstart.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sage import SageEngine
from sage.config.settings import Settings
from sage.memory.interfaces import MemorySystem
from sage.memory.models import MemoryItem, MemoryType


async def main() -> None:
    data = Path("./data/example_run")
    settings = Settings(
        env="development",
        data_dir=data,
        db_path=data / "sage.db",
        scheduler={"enabled": False},  # type: ignore[arg-type]
        plugins={"enabled": False},  # type: ignore[arg-type]
    )

    async with await SageEngine.create(settings=settings) as engine:
        print("State:", engine.state.value)
        print("Modules:", ", ".join(engine.registry.names()))

        mem = engine.container.resolve(MemorySystem)  # type: ignore[type-abstract]
        await mem.store(
            MemoryItem(
                type=MemoryType.FACT,
                content="User prefers morning planning sessions",
                importance=0.8,
                source="example",
            )
        )

        answer = await engine.ask("what do you remember about planning")
        print("\nSAGE:", answer)

        health = await engine.health()
        print("\nHealth:", health.level.value, "—", health.message)


if __name__ == "__main__":
    asyncio.run(main())
