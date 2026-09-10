"""Automation module — jobs + scheduler hooks."""

from __future__ import annotations

from sage.automation.manager import (
    AutomationJob,
    AutomationManager,
    DefaultAutomationManager,
)
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.core.scheduler import Scheduler
from sage.db.connection import Database
from sage.events.bus import EventBus
from sage.logging import get_logger

log = get_logger(__name__)


class AutomationModule(BaseModule):
    name = "automation"
    version = "0.4.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._mgr: DefaultAutomationManager | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        events = self.container.try_resolve(EventBus)
        self._mgr = DefaultAutomationManager(db, self.container, events)
        self.container.register_instance(AutomationManager, self._mgr)
        self.container.register_instance(DefaultAutomationManager, self._mgr)

        # Built-in jobs
        await self._mgr.register_job(
            AutomationJob(
                name="morning_farm_briefing",
                trigger_type="interval",
                trigger_config={"interval_seconds": 86400},
                workflow_id="morning_farm_briefing",
                metadata={
                    "task": "Daily farm briefing for tomatoes",
                    "location": "local",
                    "description": "Weather + irrigation advice",
                },
                enabled=False,  # opt-in; tests can enable
            )
        )
        await self._mgr.register_job(
            AutomationJob(
                name="sunday_financial_summary",
                trigger_type="cron",
                trigger_config={"daily_at": "09:00", "weekday": 6},
                skill_id="skill_reporting_exec_summary",
                metadata={"task": "Weekly financial summary"},
                enabled=False,
            )
        )
        await self._mgr.register_job(
            AutomationJob(
                name="on_document_ingested",
                trigger_type="event",
                trigger_config={"event_type": "knowledge.document.ingested"},
                workflow_id="document_ingest_chain",
                metadata={"task": "Document knowledge pipeline"},
                enabled=True,
            )
        )
        await self._mgr.bind_event_triggers()

    async def _on_start(self) -> None:
        if not self._mgr:
            return
        scheduler = self.container.try_resolve(Scheduler)
        if not scheduler:
            return
        mgr = self._mgr

        async def _run_enabled_interval_jobs() -> None:
            for job in await mgr.list_jobs():
                if not job.enabled:
                    continue
                if job.trigger_type == "interval":
                    # Simple: run interval jobs when scheduler fires this tick job
                    # (real cadence controlled by this registration interval)
                    try:
                        await mgr.run_job(
                            job.name,
                            context={
                                "task": job.metadata.get("task") or job.name,
                                "location": job.metadata.get("location", "local"),
                            },
                        )
                    except Exception:
                        log.exception("automation.scheduled_failed", job=job.name)

        # Default: check every hour for enabled interval automations
        scheduler.register(
            "automation.interval_dispatch",
            _run_enabled_interval_jobs,
            interval_seconds=3600.0,
            description="Dispatch enabled interval automation jobs",
        )

        # Weekly financial summary via daily_at Sunday if job enabled
        async def _sunday() -> None:
            job_list = await mgr.list_jobs()
            for job in job_list:
                if job.name == "sunday_financial_summary" and job.enabled:
                    await mgr.run_job(job.name)

        scheduler.register(
            "automation.sunday_finance",
            _sunday,
            daily_at="09:00",
            weekly_on=6,
            description="Sunday financial summary automation",
        )

    async def _on_shutdown(self) -> None:
        if self._mgr:
            await self._mgr.unbind()

    async def _on_health(self) -> HealthStatus | None:
        if self._mgr is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        jobs = await self._mgr.list_jobs()
        enabled = sum(1 for j in jobs if j.enabled)
        return HealthStatus.healthy(self.name, "ok", jobs=len(jobs), enabled=enabled)
