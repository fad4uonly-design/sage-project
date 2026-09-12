"""Event bus tests."""

from __future__ import annotations

import pytest
from sage.events.bus import InMemoryEventBus
from sage.events.events import Event


@pytest.mark.asyncio
async def test_publish_subscribe() -> None:
    bus = InMemoryEventBus()
    seen: list[str] = []

    async def handler(event: Event) -> None:
        seen.append(event.type)

    bus.subscribe("memory.item.created", handler)
    await bus.publish(Event(type="memory.item.created", payload={"x": 1}))
    assert seen == ["memory.item.created"]


@pytest.mark.asyncio
async def test_wildcard_subscribe() -> None:
    bus = InMemoryEventBus()
    seen: list[str] = []

    async def handler(event: Event) -> None:
        seen.append(event.type)

    bus.subscribe("memory.*", handler)
    await bus.publish(Event(type="memory.item.created"))
    await bus.publish(Event(type="memory.consolidated"))
    await bus.publish(Event(type="knowledge.document.ingested"))
    assert seen == ["memory.item.created", "memory.consolidated"]


@pytest.mark.asyncio
async def test_handler_error_isolated() -> None:
    bus = InMemoryEventBus()
    seen: list[int] = []

    async def bad(_e: Event) -> None:
        raise RuntimeError("boom")

    async def good(_e: Event) -> None:
        seen.append(1)

    bus.subscribe("x", bad)
    bus.subscribe("x", good)
    await bus.publish(Event(type="x"))
    assert seen == [1]
