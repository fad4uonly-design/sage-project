"""Integration: full engine boot and conversation."""

from __future__ import annotations

import pytest
from sage.core.engine import EngineState, SageEngine


@pytest.mark.asyncio
async def test_boot_and_health(engine: SageEngine) -> None:
    assert engine.state in (EngineState.RUNNING, EngineState.DEGRADED)
    health = await engine.health()
    assert health.is_ready
    names = {m.name for m in health.modules}
    for required in ("database", "memory", "conversation", "orchestrator", "knowledge"):
        assert required in names


@pytest.mark.asyncio
async def test_ask_remember_recall(engine: SageEngine) -> None:
    reply = await engine.ask("remember: My favorite crop is basil")
    assert "remember" in reply.lower() or "basil" in reply.lower()

    reply2 = await engine.ask("what do you remember about basil")
    assert "basil" in reply2.lower()


@pytest.mark.asyncio
async def test_ask_plan(engine: SageEngine) -> None:
    reply = await engine.ask("plan a weekly study schedule for Python")
    assert "step" in reply.lower() or "plan" in reply.lower() or "1." in reply


@pytest.mark.asyncio
async def test_status_dict(engine: SageEngine) -> None:
    st = engine.status_dict()
    assert st["version"]
    assert st["modules"]
    assert st["boot"]["success"] is True
