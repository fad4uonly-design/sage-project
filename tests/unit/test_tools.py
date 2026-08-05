"""Tool manager tests."""

from __future__ import annotations

import pytest

from sage.core.engine import SageEngine
from sage.tools.interfaces import ToolManager


@pytest.mark.asyncio
async def test_calculator(engine: SageEngine) -> None:
    tm = engine.container.resolve(ToolManager)  # type: ignore[type-abstract]
    result = await tm.invoke("calculator", expression="(2 + 3) * 4")
    assert result.success
    assert result.output == 20


@pytest.mark.asyncio
async def test_echo(engine: SageEngine) -> None:
    tm = engine.container.resolve(ToolManager)  # type: ignore[type-abstract]
    result = await tm.invoke("echo", text="ping")
    assert result.success
    assert result.output == "ping"
