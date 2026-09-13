"""In-process async event bus."""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sage.events.events import Event, EventHandler
from sage.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class Subscription:
    """Handle returned from subscribe — pass to unsubscribe."""

    event_type: str
    handler: EventHandler
    subscription_id: int


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, event: Event) -> None: ...

    def subscribe(self, event_type: str, handler: EventHandler) -> Subscription: ...

    def unsubscribe(self, subscription: Subscription) -> None: ...


@dataclass
class InMemoryEventBus:
    """
    Simple asyncio-friendly pub/sub bus.

    - Handlers may be sync or async.
    - Exceptions in handlers are logged and isolated (do not break other handlers).
    - Supports wildcard suffix: subscribe to "memory.*" or "*" .
    """

    _handlers: dict[str, list[tuple[int, EventHandler]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _next_id: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def subscribe(self, event_type: str, handler: EventHandler) -> Subscription:
        self._next_id += 1
        sub_id = self._next_id
        self._handlers[event_type].append((sub_id, handler))
        log.debug("event.subscribe", event_type=event_type, subscription_id=sub_id)
        return Subscription(event_type=event_type, handler=handler, subscription_id=sub_id)

    def unsubscribe(self, subscription: Subscription) -> None:
        handlers = self._handlers.get(subscription.event_type, [])
        self._handlers[subscription.event_type] = [
            (sid, h) for sid, h in handlers if sid != subscription.subscription_id
        ]

    def _matching_handlers(self, event_type: str) -> list[EventHandler]:
        matched: list[EventHandler] = []
        # Exact
        for _, handler in self._handlers.get(event_type, []):
            matched.append(handler)
        # Wildcards
        for pattern, entries in self._handlers.items():
            if pattern == event_type:
                continue
            if pattern == "*":
                matched.extend(h for _, h in entries)
            elif pattern.endswith(".*"):
                pattern[:-1]  # keep trailing dot sense: "memory."
                # pattern "memory.*" → prefix "memory."
                root = pattern[:-2]  # "memory"
                if event_type == root or event_type.startswith(root + "."):
                    matched.extend(h for _, h in entries)
        return matched

    async def publish(self, event: Event) -> None:
        handlers = self._matching_handlers(event.type)
        log.debug(
            "event.publish",
            event_type=event.type,
            event_id=event.event_id,
            handlers=len(handlers),
        )
        for handler in handlers:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception(
                    "event.handler_error",
                    event_type=event.type,
                    event_id=event.event_id,
                    handler=getattr(handler, "__qualname__", repr(handler)),
                )

    def clear(self) -> None:
        """Remove all subscriptions (primarily for tests)."""
        self._handlers.clear()
