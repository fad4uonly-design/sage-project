"""Module lifecycle protocol and base class."""

from __future__ import annotations

from abc import ABC
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sage.core.health import HealthStatus

if TYPE_CHECKING:
    from sage.core.container import Container


class ModuleState(StrEnum):
    CREATED = "created"
    INITIALIZED = "initialized"
    STARTED = "started"
    STOPPED = "stopped"
    FAILED = "failed"
    SHUTDOWN = "shutdown"


@runtime_checkable
class SageModule(Protocol):
    """Contract every SAGE subsystem must satisfy."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def is_critical(self) -> bool: ...

    @property
    def state(self) -> ModuleState: ...

    async def initialize(self) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def shutdown(self) -> None: ...

    async def health(self) -> HealthStatus: ...


class BaseModule(ABC):
    """
    Convenience base implementing state transitions.

    Subclasses override the `_on_*` hooks. The hooks default to no-ops so a
    module only implements the lifecycle events it cares about.
    """

    name: str = "base"
    version: str = "0.1.0"
    is_critical: bool = False

    def __init__(self, container: Container) -> None:
        self._container = container
        self._state = ModuleState.CREATED
        self._error: str | None = None

    @property
    def state(self) -> ModuleState:
        return self._state

    @property
    def container(self) -> Container:
        return self._container

    async def initialize(self) -> None:
        try:
            await self._on_initialize()
            self._state = ModuleState.INITIALIZED
            self._error = None
        except Exception as exc:
            self._state = ModuleState.FAILED
            self._error = str(exc)
            raise

    async def start(self) -> None:
        try:
            await self._on_start()
            self._state = ModuleState.STARTED
        except Exception as exc:
            self._state = ModuleState.FAILED
            self._error = str(exc)
            raise

    async def stop(self) -> None:
        await self._on_stop()
        self._state = ModuleState.STOPPED

    async def shutdown(self) -> None:
        await self._on_shutdown()
        self._state = ModuleState.SHUTDOWN

    async def health(self) -> HealthStatus:
        if self._state == ModuleState.FAILED:
            return HealthStatus.unhealthy(
                self.name,
                self._error or "module failed",
                critical=self.is_critical,
            )
        if self._state in (ModuleState.STARTED, ModuleState.INITIALIZED):
            custom = await self._on_health()
            if custom is not None:
                return custom
            return HealthStatus.healthy(self.name, state=self._state.value)
        if self._state == ModuleState.CREATED:
            return HealthStatus(
                name=self.name,
                level=HealthStatus.healthy(self.name).level,
                message="not yet initialized",
            )
        return HealthStatus.degraded(self.name, f"state={self._state.value}")

    # --- hooks ---

    async def _on_initialize(self) -> None:
        """Allocate resources, register services."""

    async def _on_start(self) -> None:
        """Begin background work / accept traffic."""

    async def _on_stop(self) -> None:
        """Stop background work."""

    async def _on_shutdown(self) -> None:
        """Release resources."""

    async def _on_health(self) -> HealthStatus | None:
        """Optional custom health probe. Return None to use default."""
        return None

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} state={self._state.value}>"
