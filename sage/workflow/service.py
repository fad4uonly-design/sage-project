"""Workflow module."""

from __future__ import annotations

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.logging import get_logger
from sage.workflow.builtin import all_builtin_workflows
from sage.workflow.engine import DefaultWorkflowEngine, WorkflowEngine
from sage.workflow.store import WorkflowStore

log = get_logger(__name__)


class WorkflowModule(BaseModule):
    name = "workflow"
    version = "0.4.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: DefaultWorkflowEngine | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        store = WorkflowStore(db)
        self._engine = DefaultWorkflowEngine(store, self.container)
        for wf in all_builtin_workflows():
            await self._engine.register(wf)
        self.container.register_instance(WorkflowEngine, self._engine)
        self.container.register_instance(DefaultWorkflowEngine, self._engine)
        log.info("workflow.ready", definitions=len(await self._engine.list_definitions()))

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        n = len(await self._engine.list_definitions())
        return HealthStatus.healthy(self.name, "ok", definitions=n)
