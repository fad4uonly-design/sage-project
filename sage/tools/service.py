"""Tools module."""

from __future__ import annotations

from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.logging import get_logger
from sage.tools.builtin import all_builtin_tools
from sage.tools.interfaces import ToolManager
from sage.tools.manager import DefaultToolManager
from sage.tools.verification import build_verifier

log = get_logger(__name__)


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
        pm = self.container.try_resolve(PermissionManager)
        approval = self.container.try_resolve(ApprovalEngine)
        audit = self.container.try_resolve(ExecutionAudit)

        self._manager = DefaultToolManager(
            pm,
            principal="core",
            approval_engine=approval,
            audit=audit,
            auto_approve_in_test=(settings.env == "test"),
            # Tool-R0 verification gate — the existing ToolOutputVerifier.
            # Without it the manager never stamps result.metadata["verification"],
            # leaving the verification layer dormant on the standard path.
            verifier=build_verifier(),
        )
        for tool in all_builtin_tools():
            # Respect config gates for dangerous capabilities
            if tool.name in {"write_file"} and not settings.tools.allow_shell:
                # still register write_file; approval engine gates it
                pass
            self._manager.register(tool)

        # On-demand web research: wire the EXISTING WebLearner (router-backed
        # summarizer + real memory) into the tool manager. Built lazily from the
        # running container so it reuses the live model router + memory system;
        # it only learns when explicitly invoked (never automatic/background).
        try:
            from sage.core.router_summarizer import RouterSummarizer
            from sage.core.web_learner import (
                DEFAULT_SEARCHER,
                WebLearnedMemory,
                WebLearner,
            )
            from sage.memory.index import VectorIndex
            from sage.memory.service import SQLiteMemorySystem
            from sage.models.interfaces import ModelRouter
            from sage.models.router import DefaultModelRouter
            from sage.tools.builtin.web_learn_tool import WebLearnTool

            router = self.container.try_resolve(ModelRouter)
            if router is None:
                router = self.container.try_resolve(DefaultModelRouter)
            index = self.container.try_resolve(VectorIndex)
            system = self.container.try_resolve(SQLiteMemorySystem)

            if (
                router is not None
                and index is not None
                and system is not None
                and DEFAULT_SEARCHER is not None
            ):
                embedding = router.get_embedding_model()
                memory = WebLearnedMemory(system, index, embedding=embedding)
                summarizer = RouterSummarizer(router)
                learner = WebLearner(memory, DEFAULT_SEARCHER, summarizer)
                self._manager.register(WebLearnTool(learner=learner))
                log.info("tools.web_learn_wired", router=type(router).__name__)
            else:
                missing = [
                    name
                    for name, cond in (
                        ("ModelRouter", router is None),
                        ("VectorIndex", index is None),
                        ("SQLiteMemorySystem", system is None),
                        ("SearchFn", DEFAULT_SEARCHER is None),
                    )
                    if cond
                ]
                log.warning("tools.web_learn_not_wired", missing=missing)
        except Exception:  # never let web-learn tooling break tool-module boot
            log.exception("tools.web_learn_wiring_failed")

        self.container.register_instance(ToolManager, self._manager)
        self.container.register_instance(DefaultToolManager, self._manager)

    async def _on_health(self) -> HealthStatus | None:
        if self._manager is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(
            self.name, "ok", tools=len(self._manager.list_tools())
        )
