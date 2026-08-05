"""Tools module."""

from __future__ import annotations

from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.tools.builtin import all_builtin_tools
from sage.tools.interfaces import ToolManager
from sage.tools.manager import DefaultToolManager


class ToolsModule(BaseModule):
    name = "tools"
    version = "0.4.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._manager: DefaultToolManager | None = None

    async def _on_initialize(self) -> None:
        from sage.approval.engine import ApprovalEngine
        from sage.audit.logger import ExecutionAudit
        from sage.permissions.interfaces import PermissionManager

        settings = self.container.resolve(Settings)
        pm = self.container.try_resolve(PermissionManager)  # type: ignore[type-abstract]
        approval = self.container.try_resolve(ApprovalEngine)  # type: ignore[type-abstract]
        audit = self.container.try_resolve(ExecutionAudit)  # type: ignore[type-abstract]

        self._manager = DefaultToolManager(
            pm,
            principal="core",
            approval_engine=approval,
            audit=audit,
            auto_approve_in_test=(settings.env == "test"),
        )
        for tool in all_builtin_tools():
            # Respect config gates for dangerous capabilities
            if tool.name in {"write_file"} and not settings.tools.allow_shell:
                # still register write_file; approval engine gates it
                pass
            self._manager.register(tool)

        self.container.register_instance(ToolManager, self._manager)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultToolManager, self._manager)

    async def _on_health(self) -> HealthStatus | None:
        if self._manager is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(
            self.name, "ok", tools=len(self._manager.list_tools())
        )
