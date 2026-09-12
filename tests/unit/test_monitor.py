"""Health monitor tests."""

from __future__ import annotations

import pytest
from sage.core.engine import SageEngine
from sage.monitor.interfaces import HealthMonitor


@pytest.mark.asyncio
async def test_snapshot_and_probe(engine: SageEngine) -> None:
    mon = engine.container.resolve(HealthMonitor)  # type: ignore[type-abstract]
    snap = await mon.snapshot()
    assert "rss_mb" in snap
    assert snap.get("database") == "ok"
    health = await mon.probe()
    assert health.is_ready
    recorded = await mon.record_snapshot()
    assert "health_level" in recorded
