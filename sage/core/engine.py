"""
SageEngine — the public façade for the AI operating system.

Usage:
    engine = await SageEngine.create()
    # ... use engine.container, engine.ask(), etc.
    await engine.shutdown()
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from sage import __version__
from sage.config.loader import load_settings
from sage.config.settings import Settings
from sage.core.bootstrap import BootReport, Bootstrapper
from sage.core.container import Container
from sage.core.health import SystemHealth
from sage.core.registry import ModuleRegistry
from sage.core.scheduler import Scheduler
from sage.events.bus import EventBus
from sage.logging import get_logger, setup_logging
from sage.utils.ids import new_id

log = get_logger(__name__)


class EngineState(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class SageEngine:
    """
    Central coordinator for SAGE.

    Construct via `await SageEngine.create(...)` to run the full boot sequence.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.container = Container()
        self.state = EngineState.CREATED
        self.session_id = new_id("session")
        self.bootstrapper = Bootstrapper(settings, self.container)
        self.boot_report: BootReport | None = None
        self._register_default_modules()

    @classmethod
    async def create(
        cls,
        *,
        settings: Settings | None = None,
        config_file: str | None = None,
        overrides: dict[str, Any] | None = None,
        setup_logs: bool = True,
    ) -> SageEngine:
        """Load config, initialize logging, boot all modules, return running engine."""
        if settings is None:
            settings = load_settings(config_file=config_file, overrides=overrides)

        engine = cls(settings)

        if setup_logs:
            setup_logging(
                level=settings.logging.level,
                log_format=settings.logging.format,
                log_dir=settings.data_dir / "logs",
                session_id=engine.session_id,
            )

        log.info(
            "engine.creating",
            version=__version__,
            env=settings.env,
            session_id=engine.session_id,
        )

        engine.state = EngineState.STARTING
        report = await engine.bootstrapper.boot()
        engine.boot_report = report

        if not report.success:
            engine.state = EngineState.FAILED
            raise RuntimeError(report.error or "SAGE boot failed")

        if report.health and report.health.level.value == "degraded":
            engine.state = EngineState.DEGRADED
        else:
            engine.state = EngineState.RUNNING

        engine.container.register_instance(SageEngine, engine)
        await engine._register_system_jobs()
        return engine

    def _register_default_modules(self) -> None:
        """
        Register the full module graph in dependency order.

        v0.1.1 foundation:
          database → secrets → permissions → config → memory → …
          → orchestrator → conversation
        """
        from sage.agents.service import AgentModule
        from sage.capabilities.service import CapabilitiesModule
        from sage.config.service import ConfigModule
        from sage.conversation.service import ConversationModule
        from sage.db.service import DatabaseModule
        from sage.decision.service import DecisionModule
        from sage.files.service import FileModule
        from sage.knowledge.service import KnowledgeModule
        from sage.learning.service import LearningModule
        from sage.memory.service import MemoryModule
        from sage.models.service import ModelsModule
        from sage.monitor.service import MonitorModule
        from sage.orchestrator.service import OrchestratorModule
        from sage.permissions.service import PermissionsModule
        from sage.planning.service import PlanningModule
        from sage.plugins.service import PluginModule
        from sage.reasoning.service import ReasoningModule
        from sage.retrieval.service import RetrievalModule
        from sage.secrets.service import SecretsModule
        from sage.tools.service import ToolsModule

        b = self.bootstrapper
        # Foundation
        b.register_module("database", lambda c: DatabaseModule(c), critical=True)
        b.register_module("secrets", lambda c: SecretsModule(c), critical=False)
        b.register_module("permissions", lambda c: PermissionsModule(c), critical=True)
        b.register_module("config", lambda c: ConfigModule(c), critical=True)
        b.register_module("memory", lambda c: MemoryModule(c), critical=True)
        # Intelligence layer
        b.register_module("knowledge", lambda c: KnowledgeModule(c), critical=False)
        b.register_module("models", lambda c: ModelsModule(c), critical=False)
        b.register_module("retrieval", lambda c: RetrievalModule(c), critical=False)
        b.register_module("reasoning", lambda c: ReasoningModule(c), critical=False)
        b.register_module("learning", lambda c: LearningModule(c), critical=False)
        b.register_module("planning", lambda c: PlanningModule(c), critical=False)
        b.register_module("decision", lambda c: DecisionModule(c), critical=False)
        b.register_module("tools", lambda c: ToolsModule(c), critical=False)
        b.register_module("capabilities", lambda c: CapabilitiesModule(c), critical=False)
        # Domain intelligence
        b.register_module("agents", lambda c: AgentModule(c), critical=False)
        b.register_module("plugins", lambda c: PluginModule(c), critical=False)
        b.register_module("files", lambda c: FileModule(c), critical=False)
        b.register_module("orchestrator", lambda c: OrchestratorModule(c), critical=True)
        b.register_module("monitor", lambda c: MonitorModule(c), critical=False)
        b.register_module("conversation", lambda c: ConversationModule(c), critical=True)

    async def _register_system_jobs(self) -> None:
        """Built-in maintenance jobs on the real scheduler."""
        if not self.settings.scheduler.enabled:
            return
        scheduler = self.scheduler

        async def _audit_heartbeat() -> None:
            from sage.logging import audit

            health = await self.health()
            audit(
                "heartbeat",
                state=self.state.value,
                health=health.level.value,
                modules=len(health.modules),
            )

        scheduler.register(
            "system.heartbeat",
            _audit_heartbeat,
            interval_seconds=600.0,
            description="Audit heartbeat every 10 minutes",
        )

        # Daily placeholder for backup hook (actual backup in later milestone)
        async def _daily_maintenance() -> None:
            from sage.logging import audit
            from sage.memory.interfaces import MemorySystem

            mem = self.container.try_resolve(MemorySystem)  # type: ignore[type-abstract]
            if mem:
                report = await mem.consolidate()
                audit("daily_maintenance", consolidation=report.model_dump())
            else:
                audit("daily_maintenance", consolidation=None)

        scheduler.register(
            "system.daily_maintenance",
            _daily_maintenance,
            daily_at="03:30",
            timezone="UTC",
            description="Nightly consolidation / maintenance",
        )

    @property
    def events(self) -> EventBus:
        return self.container.resolve(EventBus)  # type: ignore[type-abstract]

    @property
    def registry(self) -> ModuleRegistry:
        return self.container.resolve(ModuleRegistry)

    @property
    def scheduler(self) -> Scheduler:
        return self.container.resolve(Scheduler)

    async def health(self) -> SystemHealth:
        from sage.monitor.interfaces import HealthMonitor

        mon = self.container.try_resolve(HealthMonitor)  # type: ignore[type-abstract]
        if mon is not None:
            return await mon.probe()
        return await self.bootstrapper.collect_health()

    def status_dict(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "state": self.state.value,
            "session_id": self.session_id,
            "env": self.settings.env,
            "modules": self.registry.names(),
            "boot": self.boot_report.to_payload() if self.boot_report else None,
            "jobs": self.scheduler.list_jobs() if self.container.has(Scheduler) else [],
        }

    async def ask(self, message: str, *, user_id: str | None = None) -> str:
        """One-shot convenience via Conversation Engine → Orchestrator."""
        from sage.conversation.interfaces import ConversationEngine

        conv = self.container.resolve(ConversationEngine)  # type: ignore[type-abstract]
        uid = user_id or self.settings.conversation.default_user_id
        session = await conv.start_session(user_id=uid)
        try:
            turn = await conv.respond(session.id, message)
            return turn.assistant_message
        finally:
            await conv.end_session(session.id)

    async def shutdown(self) -> None:
        if self.state in (EngineState.STOPPED, EngineState.STOPPING):
            return
        self.state = EngineState.STOPPING
        log.info("engine.shutdown")
        await self.bootstrapper.shutdown()
        self.state = EngineState.STOPPED
        log.info("engine.stopped")

    async def __aenter__(self) -> SageEngine:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.shutdown()
