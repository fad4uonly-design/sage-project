"""Shared pytest fixtures for SAGE."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

from sage.config.settings import Settings
from sage.core.engine import SageEngine


@pytest_asyncio.fixture
async def tmp_settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        env="test",
        data_dir=data,
        db_path=data / "test_sage.db",
        logging={"level": "WARNING", "format": "console"},  # type: ignore[arg-type]
        scheduler={"enabled": False},  # type: ignore[arg-type]
        plugins={"enabled": False, "auto_load": False},  # type: ignore[arg-type]
    )


@pytest_asyncio.fixture
async def engine(tmp_settings: Settings) -> AsyncIterator[SageEngine]:
    eng = await SageEngine.create(settings=tmp_settings, setup_logs=True)
    try:
        yield eng
    finally:
        await eng.shutdown()
