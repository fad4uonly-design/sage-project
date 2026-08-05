"""Capability registry tests."""

from __future__ import annotations

import pytest

from sage.capabilities.interfaces import CapabilityRegistry
from sage.capabilities.models import CapabilityDescriptor
from sage.core.engine import SageEngine


@pytest.mark.asyncio
async def test_builtin_capabilities(engine: SageEngine) -> None:
    reg = engine.container.resolve(CapabilityRegistry)  # type: ignore[type-abstract]
    all_caps = await reg.list_all()
    assert len(all_caps) >= 6
    domains = {c.domain for c in all_caps}
    assert "agriculture" in domains
    assert "finance" in domains
    assert "planning" in domains


@pytest.mark.asyncio
async def test_find_for_task(engine: SageEngine) -> None:
    reg = engine.container.resolve(CapabilityRegistry)  # type: ignore[type-abstract]
    matches = await reg.find_for_task("help me plan irrigation for tomato crops")
    assert matches
    top = matches[0][0]
    assert top.domain in {"agriculture", "planning", "general"}


@pytest.mark.asyncio
async def test_register_custom(engine: SageEngine) -> None:
    reg = engine.container.resolve(CapabilityRegistry)  # type: ignore[type-abstract]
    desc = CapabilityDescriptor(
        principal="custom_bot",
        domain="testing",
        capabilities=["test", "verify"],
        reasoning_strategies=["logical"],
        confidence_threshold=0.1,
    )
    await reg.register(desc)
    found = await reg.get("custom_bot", "testing")
    assert found is not None
    assert "test" in found.capabilities
