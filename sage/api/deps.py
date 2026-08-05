"""FastAPI dependencies — shared engine handle."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sage.core.engine import SageEngine

_engine: SageEngine | None = None


def set_engine(engine: SageEngine) -> None:
    global _engine
    _engine = engine


def get_engine() -> SageEngine:
    if _engine is None:
        raise RuntimeError("SAGE engine not bound to API")
    return _engine
