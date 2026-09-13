"""Health monitor — resource probes + module health aggregation."""

from __future__ import annotations

import ctypes
import os
import platform

try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]

from typing import Any

from sage.core.container import Container
from sage.core.health import HealthStatus, SystemHealth
from sage.core.module import BaseModule
from sage.core.registry import ModuleRegistry
from sage.core.scheduler import Scheduler
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event, SystemEvents
from sage.logging import get_logger
from sage.monitor.interfaces import HealthMonitor
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


def _cpu_percent_approx() -> float | None:
    """
    Best-effort CPU usage estimation.

    Linux/macOS:
        Uses load average.

    Windows:
        Returns None without psutil dependency.
    """
    try:
        if hasattr(os, "getloadavg"):
            load1, _, _ = os.getloadavg()
            cpus = os.cpu_count() or 1
            return float(round(min(100.0, (load1 / cpus) * 100.0), 1))

    except Exception:
        pass

    return None


def _windows_rss_mb() -> float:
    """
    Windows process working set memory.
    """
    try:
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)

        handle = ctypes.windll.kernel32.GetCurrentProcess()

        result = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )

        if result:
            return float(round(counters.WorkingSetSize / (1024 * 1024), 2))

    except Exception:
        pass

    return 0.0


def _rss_mb() -> float:
    """
    Cross-platform RSS memory usage.
    """

    try:
        system = platform.system()

        if system == "Windows":
            return _windows_rss_mb()

        if resource:
            usage = resource.getrusage(resource.RUSAGE_SELF)  # type: ignore[attr-defined]

            # Linux reports KB
            if system == "Linux":
                return float(round(usage.ru_maxrss / 1024.0, 2))

            # macOS reports bytes
            if system == "Darwin":
                return float(round(usage.ru_maxrss / (1024 * 1024), 2))

    except Exception as exc:
        log.debug(
            "monitor.memory_probe_failed",
            error=str(exc),
        )

    return 0.0


class DefaultHealthMonitor(BaseRepository):
    def __init__(
        self,
        db: Database,
        registry: ModuleRegistry,
        events: EventBus | None = None,
    ) -> None:
        super().__init__(db)
        self._registry = registry
        self._events = events
        self._last: dict[str, Any] | None = None

    async def snapshot(self) -> dict[str, Any]:
        cpu = _cpu_percent_approx()
        rss = _rss_mb()

        snap: dict[str, Any] = {
            "cpu_percent": cpu,
            "memory_percent": None,
            "rss_mb": rss,
            "pid": os.getpid(),
            "platform": platform.system(),
            "modules": self._registry.names(),
            "timestamp": utcnow_iso(),
        }

        try:
            await self.db.scalar("SELECT 1")
            snap["database"] = "ok"

        except Exception as exc:
            snap["database"] = f"error:{exc}"

        self._last = snap

        return snap

    async def probe(self) -> SystemHealth:
        statuses: list[HealthStatus] = []

        for module in self._registry.all():
            try:
                status = await module.health()

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

        snap = await self.snapshot()

        rss = float(snap.get("rss_mb") or 0)

        if rss > 1024:
            statuses.append(
                HealthStatus.degraded(
                    "resources",
                    f"high rss_mb={rss}",
                    rss_mb=rss,
                )
            )
        else:
            statuses.append(
                HealthStatus.healthy(
                    "resources",
                    "ok",
                    rss_mb=rss,
                    cpu_percent=snap.get("cpu_percent"),
                )
            )

        health = SystemHealth.from_modules(statuses)

        if health.level.value == "degraded" and self._events:
            await self._events.publish(
                Event(
                    type=SystemEvents.HEALTH_DEGRADED,
                    payload={"message": health.message},
                    source="monitor",
                )
            )

        return health

    async def record_snapshot(self) -> dict[str, Any]:
        snap = await self.snapshot()
        health = await self.probe()

        payload = {
            **snap,
            "health_level": health.level.value,
            "health_message": health.message,
        }

        await self.db.execute(
            """
            INSERT INTO health_snapshots
            (id, level, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                new_id("hlth"),
                health.level.value,
                self.dumps(payload),
                utcnow_iso(),
            ),
        )

        await self.db.execute(
            """
            DELETE FROM health_snapshots
            WHERE id NOT IN (
                SELECT id
                FROM health_snapshots
                ORDER BY created_at DESC
                LIMIT 500
            )
            """
        )

        log.debug(
            "monitor.snapshot_recorded",
            level=health.level.value,
            rss_mb=snap.get("rss_mb"),
        )

        return payload


class MonitorModule(BaseModule):
    name = "monitor"
    version = "0.1.2"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._mon: DefaultHealthMonitor | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        registry = self.container.resolve(ModuleRegistry)
        events = self.container.try_resolve(EventBus)

        self._mon = DefaultHealthMonitor(
            db,
            registry,
            events,
        )

        self.container.register_instance(
            HealthMonitor,
            self._mon,
        )

        self.container.register_instance(
            DefaultHealthMonitor,
            self._mon,
        )

    async def _on_start(self) -> None:
        scheduler = self.container.try_resolve(Scheduler)

        if scheduler and self._mon:
            mon = self._mon

            async def _job() -> None:
                await mon.record_snapshot()

            scheduler.register(
                "monitor.snapshot",
                _job,
                interval_seconds=300.0,
            )

    async def _on_health(self) -> HealthStatus | None:
        if self._mon is None:
            return HealthStatus.unhealthy(
                self.name,
                "not initialized",
            )

        snap = await self._mon.snapshot()

        return HealthStatus.healthy(
            self.name,
            "ok",
            rss_mb=snap.get("rss_mb"),
            cpu_percent=snap.get("cpu_percent"),
        )
