"""Minimal background scheduler for periodic jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sage.logging import get_logger
from sage.utils.time import utcnow_iso

log = get_logger(__name__)

JobFunc = Callable[[], Awaitable[None] | None]


@dataclass(slots=True)
class Job:
    name: str
    func: JobFunc
    interval_seconds: float
    last_run: str | None = None
    run_count: int = 0
    enabled: bool = True


@dataclass
class Scheduler:
    """
    Cooperative asyncio scheduler.

    Not a replacement for cron — good enough for memory consolidation,
    health pings, and light maintenance in-process.
    """

    tick_seconds: float = 60.0
    _jobs: dict[str, Job] = field(default_factory=dict)
    _task: asyncio.Task[None] | None = None
    _running: bool = False
    _elapsed: dict[str, float] = field(default_factory=dict)

    def register(self, name: str, func: JobFunc, *, interval_seconds: float) -> None:
        self._jobs[name] = Job(name=name, func=func, interval_seconds=interval_seconds)
        self._elapsed[name] = 0.0
        log.debug("scheduler.job_registered", job=name, interval=interval_seconds)

    def unregister(self, name: str) -> None:
        self._jobs.pop(name, None)
        self._elapsed.pop(name, None)

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
            self._elapsed[name] = self._elapsed.get(name, 0.0) + self.tick_seconds
            if self._elapsed[name] >= job.interval_seconds:
                self._elapsed[name] = 0.0
                await self._run_job(job)

    async def _run_job(self, job: Job) -> None:
        log.debug("scheduler.job_run", job=job.name)
        try:
            result = job.func()
            if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                await result  # type: ignore[arg-type]
            job.last_run = utcnow_iso()
            job.run_count += 1
        except Exception:
            log.exception("scheduler.job_error", job=job.name)

    def list_jobs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": j.name,
                "interval_seconds": j.interval_seconds,
                "last_run": j.last_run,
                "run_count": j.run_count,
                "enabled": j.enabled,
            }
            for j in self._jobs.values()
        ]
