"""Unit tests for the core scheduler calendar path (daily/weekly jobs).

Regression coverage for the Windows-only ``ZoneInfoNotFoundError`` crash:
``_should_run_calendar`` used to fall back to ``ZoneInfo("UTC")`` when a
zone lookup failed, which raised the same error on machines without a tz
database (Windows without the ``tzdata`` package). The fallback must always
resolve to a working UTC so daily/weekly jobs never kill the scheduler task.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from zoneinfo import ZoneInfoNotFoundError

import sage.core.scheduler as scheduler_module
from sage.core.scheduler import Scheduler

# Frozen clock: 15s past the daily target, inside the fire window
# (0 <= delta < tick_seconds * 2 = 30s). Date matches the real today so
# last_run_date dedup (set from real utcnow) lines up with date_key.
_REAL_NOW = datetime.now(UTC)
FROZEN_NOW = _REAL_NOW.replace(hour=13, minute=30, second=15, microsecond=0)
DAILY_AT = "13:30"


class _FrozenDatetime(datetime):
    """``datetime`` whose ``now()`` always returns the frozen instant."""

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return FROZEN_NOW


def _make_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    *,
    timezone: str = "UTC",
    zoneinfo_always_raises: bool = False,
) -> tuple[Scheduler, list[int]]:
    """Build a scheduler with one daily job at DAILY_AT; return (scheduler, call log)."""
    calls: list[int] = []

    async def job() -> None:
        calls.append(1)

    if zoneinfo_always_raises:

        def _boom(name: str) -> Any:
            raise ZoneInfoNotFoundError(name)

        monkeypatch.setattr(scheduler_module, "ZoneInfo", _boom)

    monkeypatch.setattr(scheduler_module, "datetime", _FrozenDatetime)

    scheduler = Scheduler(tick_seconds=15.0)
    scheduler.register("daily_test", job, daily_at=DAILY_AT, timezone=timezone)
    return scheduler, calls


async def test_daily_job_fires_even_without_tz_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a failing ZoneInfo lookup (Windows w/o tzdata) must not
    crash the calendar path — the stdlib UTC fallback fires the job."""
    scheduler, calls = _make_scheduler(monkeypatch, zoneinfo_always_raises=True)

    await scheduler._tick()

    assert calls == [1]


async def test_unknown_timezone_falls_back_to_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolvable zone name must fall back to UTC, not kill the tick."""
    scheduler, calls = _make_scheduler(monkeypatch, timezone="Mars/Olympus")

    await scheduler._tick()

    assert calls == [1]


async def test_daily_job_runs_once_per_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The date-key dedup must prevent a second fire on the same day."""
    scheduler, calls = _make_scheduler(monkeypatch, zoneinfo_always_raises=True)

    await scheduler._tick()
    await scheduler._tick()

    assert calls == [1]
