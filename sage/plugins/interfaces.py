"""Plugin protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sage.plugins.manifest import PluginManifest

if TYPE_CHECKING:
    from sage.core.container import Container


@runtime_checkable
class Plugin(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    async def on_load(self, container: Container) -> None: ...

    async def on_unload(self) -> None: ...
