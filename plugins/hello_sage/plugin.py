"""Example SAGE plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sage.plugins.manifest import PluginManifest

if TYPE_CHECKING:
    from sage.core.container import Container


class HelloPlugin:
    def __init__(self) -> None:
        self._manifest = PluginManifest(
            id="hello_sage",
            name="Hello SAGE",
            version="0.1.0",
            description="Example plugin that logs a greeting on load",
        )

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    async def on_load(self, container: Container) -> None:
        from sage.logging import get_logger

        log = get_logger("plugin.hello_sage")
        log.info("hello_sage.loaded", msg="Hello from the example SAGE plugin!")

    async def on_unload(self) -> None:
        from sage.logging import get_logger

        get_logger("plugin.hello_sage").info("hello_sage.unloaded")
