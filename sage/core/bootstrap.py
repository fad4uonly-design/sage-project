"""
Ordered startup and shutdown of SAGE modules.

The bootstrapper owns the sequence documented in docs/architecture/STARTUP.md.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sage.core.container import Container
from sage.core.health import HealthStatus, SystemHealth
from sage.core.module import BaseModule, SageModule
from sage.core.registry import ModuleRegistry
from sage.core.scheduler import Scheduler
from sage.events.bus import EventBus, InMemoryEventBus
from sage.events.events import Event, SystemEvents
from sage.logging import get_logger

if TYPE_CHECKING:
    from sage.config.settings import Settings

log = get_logger(__name__)

# Factory: (container) -> module instance
ModuleFactory = Callable[[Container], SageModule]


@dataclass
class BootReport:
    """Metrics emitted after a successful (or partial) boot."""

    success: bool
    boot_duration_ms: float
    modules_initialized: list[str] = field(default_factory=list)
    modules_failed: list[str] = field(default_factory=list)
    plugins_loaded: list[str] = field(default_factory=list)
    health: SystemHealth | None = None
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "boot_duration_ms": self.boot_duration_ms,
            "modules_initialized": self.modules_initialized,
            "modules_failed": self.modules_failed,
            "plugins_loaded": self.plugins_loaded,
            "health_level": self.health.level.value if self.health else None,
            "error": self.error,
        }


class BootstrapError(Exception):
    """Fatal boot failure."""


class Bootstrapper:
    """
    Constructs infrastructure and initializes modules in dependency order.
    """

    def __init__(self, settings: Settings, container: Container | None = None) -> None:
        self.settings = settings
        self.container = container or Container()
        self.registry = ModuleRegistry()
        self.event_bus: EventBus = InMemoryEventBus()
        self.scheduler = Scheduler(tick_seconds=float(settings.scheduler.tick_seconds))
        self._module_factories: list[tuple[str, ModuleFactory, bool]] = []
        # (name, factory, critical)

    def register_module(
        self,
        name: str,
        factory: ModuleFactory,
        *,
        critical: bool = False,
    ) -> None:
        """Queue a module to be initialized during boot (order = registration order)."""
        self._module_factories.append((name, factory, critical))

    def _register_infrastructure(self) -> None:
        self.container.register_instance(type(self.settings), self.settings)
        # Also under plain Settings name if different
        from sage.config.settings import Settings as SettingsType

        if not self.container.has(SettingsType):
            self.container.register_instance(SettingsType, self.settings)

        self.container.register_instance(Container, self.container)
        self.container.register_instance(EventBus, self.event_bus)
        self.container.register_instance(InMemoryEventBus, self.event_bus)
        self.container.register_instance(ModuleRegistry, self.registry)
        self.container.register_instance(Scheduler, self.scheduler)

        # Expose the EXISTING sage.memory.index.VectorIndex through normal DI so
        # components like MemoryInterface can resolve it instead of rebuilding it.
        # Lazy factory: Database + ModelRouter are registered by their modules
        # later, so the index is only materialized when actually resolved.
        from sage.memory.index import VectorIndex

        def _build_vector_index(c: Container) -> VectorIndex:
            from sage.db.connection import Database
            from sage.memory.index import SqliteVectorIndex
            from sage.models.interfaces import ModelRouter

            index = SqliteVectorIndex(c.resolve(Database))
            router = c.try_resolve(ModelRouter)
            if router is not None:
                try:
                    index.attach(router.get_embedding_model())
                except Exception as exc:  # never break boot over embedding attach
                    log.debug("bootstrap.vector_index_attach_failed", error=str(exc))
            return index

        self.container.register_factory(VectorIndex, _build_vector_index)

    async def boot(self) -> BootReport:
        started = time.perf_counter()
        initialized: list[str] = []
        failed: list[str] = []

        log.info("bootstrap.start", env=self.settings.env)

        try:
            self.settings.ensure_directories()
            self._register_infrastructure()

            for name, factory, critical in self._module_factories:
                try:
                    log.info("bootstrap.module_init", module=name)
                    module = factory(self.container)
                    # Align critical flag if BaseModule
                    if isinstance(module, BaseModule):
                        module.is_critical = critical or module.is_critical
                    await module.initialize()
                    self.registry.register(module)
                    initialized.append(name)
                    await self.event_bus.publish(
                        Event(
                            type=SystemEvents.MODULE_INITIALIZED,
                            payload={"module": name},
                            source="bootstrap",
                        )
                    )
                except Exception as exc:
                    log.exception("bootstrap.module_failed", module=name)
                    failed.append(name)
                    await self.event_bus.publish(
                        Event(
                            type=SystemEvents.MODULE_FAILED,
                            payload={"module": name, "error": str(exc)},
                            source="bootstrap",
                        )
                    )
                    if critical:
                        duration = (time.perf_counter() - started) * 1000
                        report = BootReport(
                            success=False,
                            boot_duration_ms=duration,
                            modules_initialized=initialized,
                            modules_failed=failed,
                            error=f"Critical module failed: {name}: {exc}",
                        )
                        return report

            # Start modules
            for module in self.registry.all():
                try:
                    await module.start()
                except Exception as exc:
                    log.exception("bootstrap.module_start_failed", module=module.name)
                    failed.append(module.name)
                    if module.is_critical:
                        duration = (time.perf_counter() - started) * 1000
                        return BootReport(
                            success=False,
                            boot_duration_ms=duration,
                            modules_initialized=initialized,
                            modules_failed=failed,
                            error=f"Critical module start failed: {module.name}: {exc}",
                        )

            if self.settings.scheduler.enabled:
                await self.scheduler.start()

            health = await self.collect_health()
            duration = (time.perf_counter() - started) * 1000

            if not health.is_ready:
                return BootReport(
                    success=False,
                    boot_duration_ms=duration,
                    modules_initialized=initialized,
                    modules_failed=failed,
                    health=health,
                    error="System health not ready after boot",
                )

            report = BootReport(
                success=True,
                boot_duration_ms=duration,
                modules_initialized=initialized,
                modules_failed=failed,
                health=health,
            )

            await self.event_bus.publish(
                Event(
                    type=SystemEvents.READY,
                    payload=report.to_payload(),
                    source="bootstrap",
                )
            )
            log.info(
                "bootstrap.ready",
                duration_ms=round(duration, 2),
                modules=initialized,
                failed=failed,
            )
            return report

        except Exception as exc:
            duration = (time.perf_counter() - started) * 1000
            log.exception("bootstrap.fatal")
            return BootReport(
                success=False,
                boot_duration_ms=duration,
                modules_initialized=initialized,
                modules_failed=failed,
                error=str(exc),
            )

    async def shutdown(self, modules: Sequence[SageModule] | None = None) -> None:
        log.info("bootstrap.shutdown")
        await self.event_bus.publish(
            Event(type=SystemEvents.SHUTTING_DOWN, source="bootstrap")
        )

        await self.scheduler.stop()

        mods = list(modules) if modules is not None else list(reversed(self.registry.all()))
        for module in mods:
            try:
                await module.stop()
            except Exception:
                log.exception("bootstrap.stop_failed", module=module.name)
        for module in mods:
            try:
                await module.shutdown()
            except Exception:
                log.exception("bootstrap.shutdown_failed", module=module.name)

        log.info("bootstrap.shutdown_complete")

    async def collect_health(self) -> SystemHealth:
        statuses: list[HealthStatus] = []
        for module in self.registry.all():
            try:
                status = await module.health()
                # Ensure critical flag reflects module
                if module.is_critical:
                    status.critical = True
                statuses.append(status)
            except Exception as exc:
                statuses.append(
                    HealthStatus.unhealthy(
                        module.name,
                        f"health check raised: {exc}",
                        critical=module.is_critical,
                    )
                )
        return SystemHealth.from_modules(statuses)
