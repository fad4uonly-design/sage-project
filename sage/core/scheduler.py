"""Background scheduler with interval and cron-like daily/weekly jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

from sage.logging import get_logger
from sage.utils.time import utcnow, utcnow_iso

log = get_logger(__name__)

JobFunc = Callable[[], Awaitable[None] | None]


class JobKind(str, Enum):
    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass(slots=True)
class Job:
    name: str
    func: JobFunc
    kind: JobKind = JobKind.INTERVAL
    interval_seconds: float = 60.0
    # daily/weekly: run at local time (default UTC)
    at_time: time | None = None
    weekday: int | None = None  # 0=Monday … 6=Sunday for WEEKLY
    timezone: str = "UTC"
    last_run: str | None = None
    last_run_date: str | None = None  # YYYY-MM-DD for daily/weekly dedup
    run_count: int = 0
    enabled: bool = True
    description: str = ""


@dataclass
class Scheduler:
    """
    Cooperative asyncio scheduler.

    Supports:
      - interval jobs (every N seconds)
      - daily jobs at HH:MM
      - weekly jobs on a weekday at HH:MM

    Good enough for memory consolidation, backups, health snapshots,
    and light maintenance without an external cron daemon.
    """

    tick_seconds: float = 15.0
    _jobs: dict[str, Job] = field(default_factory=dict)
    _task: asyncio.Task[None] | None = None
    _running: bool = False
    _elapsed: dict[str, float] = field(default_factory=dict)

    def register(
        self,
        name: str,
        func: JobFunc,
        *,
        interval_seconds: float | None = None,
        daily_at: str | None = None,
        weekly_on: int | None = None,
        timezone: str = "UTC",
        description: str = "",
    ) -> None:
        """
        Register a job.

        Provide one of:
          - interval_seconds
          - daily_at="HH:MM" (optionally with weekly_on=0-6)
        """
        if daily_at is not None:
            hour, minute = (int(x) for x in daily_at.split(":", 1))
            at = time(hour=hour, minute=minute)
            kind = JobKind.WEEKLY if weekly_on is not None else JobKind.DAILY
            job = Job(
                name=name,
                func=func,
                kind=kind,
                at_time=at,
                weekday=weekly_on,
                timezone=timezone,
                description=description,
            )
        else:
            if interval_seconds is None:
                raise ValueError("Provide interval_seconds or daily_at")
            job = Job(
                name=name,
                func=func,
                kind=JobKind.INTERVAL,
                interval_seconds=float(interval_seconds),
                description=description,
            )
            self._elapsed[name] = 0.0

        self._jobs[name] = job
        log.debug(
            "scheduler.job_registered",
            job=name,
            kind=job.kind.value,
            interval=job.interval_seconds,
            daily_at=daily_at,
            weekly_on=weekly_on,
        )

    def unregister(self, name: str) -> None:
        self._jobs.pop(name, None)
        self._elapsed.pop(name, None)

    def enable(self, name: str, enabled: bool = True) -> None:
        if name in self._jobs:
            self._jobs[name].enabled = enabled

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="sage-scheduler")
        log.info("scheduler.started", tick=self.tick_seconds, jobs=len(self._jobs))

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("scheduler.stopped")

    async def run_now(self, name: str) -> None:
        job = self._jobs.get(name)
        if job is None:
            raise KeyError(name)
        await self._run_job(job)

    async def _loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self.tick_seconds)
                await self._tick()
        except asyncio.CancelledError:
            raise

    async def _tick(self) -> None:
        for name, job in list(self._jobs.items()):
            if not job.enabled:
                continue
            if job.kind == JobKind.INTERVAL:
                self._elapsed[name] = self._elapsed.get(name, 0.0) + self.tick_seconds
                if self._elapsed[name] >= job.interval_seconds:
                    self._elapsed[name] = 0.0
                    await self._run_job(job)
            else:
                if self._should_run_calendar(job):
                    await self._run_job(job)

    def _should_run_calendar(self, job: Job) -> bool:
        if job.at_time is None:
            return False
        try:
            tz = ZoneInfo(job.timezone)
        except Exception:
            tz = ZoneInfo("UTC")
        now = datetime.now(tz)
        date_key = now.date().isoformat()
        if job.last_run_date == date_key:
            return False
        if job.kind == JobKind.WEEKLY and job.weekday is not None:
            if now.weekday() != job.weekday:
                return False
        target = now.replace(
            hour=job.at_time.hour,
            minute=job.at_time.minute,
            second=0,
            microsecond=0,
        )
        # Fire in the first tick window after target time
        delta = (now - target).total_seconds()
        return 0 <= delta < self.tick_seconds * 2

    async def _run_job(self, job: Job) -> None:
        log.debug("scheduler.job_run", job=job.name, kind=job.kind.value)
        try:
            result = job.func()
            if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                await result  # type: ignore[arg-type]
            job.last_run = utcnow_iso()
            job.last_run_date = utcnow().date().isoformat()
            job.run_count += 1
        except Exception:
            log.exception("scheduler.job_error", job=job.name)

    def list_jobs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": j.name,
                "kind": j.kind.value,
                "interval_seconds": j.interval_seconds,
                "at_time": j.at_time.isoformat(timespec="minutes") if j.at_time else None,
                "weekday": j.weekday,
                "timezone": j.timezone,
                "last_run": j.last_run,
                "run_count": j.run_count,
                "enabled": j.enabled,
                "description": j.description,
            }
            for j in self._jobs.values()
        ]
