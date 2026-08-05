"""API module — starts uvicorn when settings.api.enabled."""

from __future__ import annotations

import asyncio
from typing import Any

from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.logging import get_logger

log = get_logger(__name__)


class APIModule(BaseModule):
    name = "api"
    version = "0.6.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._server: Any = None
        self._task: asyncio.Task[None] | None = None
        self._port: int | None = None

    async def _on_initialize(self) -> None:
        # App is created at start when engine is fully registered
        pass

    async def _on_start(self) -> None:
        settings = self.container.resolve(Settings)
        if not settings.api.enabled:
            log.info("api.disabled")
            return
        from sage.api.app import create_app
        from sage.core.engine import SageEngine

        engine = self.container.resolve(SageEngine)
        app = create_app(engine)

        import uvicorn

        host = settings.api.host or "0.0.0.0"
        # Preview environments need 0.0.0.0
        if host in {"127.0.0.1", "localhost"}:
            host = "0.0.0.0"
        port = int(settings.api.port or 8742)
        self._port = port
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve(), name="sage-api")
        log.info("api.started", host=host, port=port)

    async def _on_stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        self._server = None

    async def _on_health(self) -> HealthStatus | None:
        settings = self.container.resolve(Settings)
        if not settings.api.enabled:
            return HealthStatus.healthy(self.name, "disabled")
        if self._task and not self._task.done():
            return HealthStatus.healthy(self.name, "serving", port=self._port)
        return HealthStatus.degraded(self.name, "enabled but not serving")
