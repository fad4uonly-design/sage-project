"""Capability registry protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sage.capabilities.models import CapabilityDescriptor


@runtime_checkable
class CapabilityRegistry(Protocol):
    async def register(self, descriptor: CapabilityDescriptor) -> CapabilityDescriptor: ...

    async def unregister(self, principal: str, domain: str) -> bool: ...

    async def find_for_domain(self, domain: str) -> list[CapabilityDescriptor]: ...

    async def find_for_task(self, description: str) -> list[tuple[CapabilityDescriptor, float]]: ...

    async def list_all(self) -> list[CapabilityDescriptor]: ...

    async def get(self, principal: str, domain: str) -> CapabilityDescriptor | None: ...
