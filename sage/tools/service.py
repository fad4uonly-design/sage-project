"""Tools module."""

from __future__ import annotations

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.tools.builtin import CalculatorTool, EchoTool, TimeTool
from sage.tools.interfaces import ToolManager
from sage.tools.manager import DefaultToolManager


class ToolsModule(BaseModule):
    name = "tools"
    version = "0.1.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._manager: DefaultToolManager | None = None

    async def _on_initialize(self) -> None:
        from sage.permissions.interfaces import PermissionManager

        pm = self.container.try_resolve(PermissionManager)  # type: ignore[type-abstract]
        self._manager = DefaultToolManager(pm, principal="core")
        for tool in (EchoTool(), TimeTool(), CalculatorTool()):
            self._manager.register(tool)
        self.container.register_instance(ToolManager, self._manager)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultToolManager, self._manager)

    async def _on_health(self) -> HealthStatus | None:
        if self._manager is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(self.name, "ok", tools=len(self._manager.list_tools()))
