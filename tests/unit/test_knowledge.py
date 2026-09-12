"""Knowledge manager tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from sage.core.engine import SageEngine
from sage.knowledge.interfaces import KnowledgeManager


@pytest.mark.asyncio
async def test_ingest_and_search(engine: SageEngine, tmp_path: Path) -> None:
    km = engine.container.resolve(KnowledgeManager)  # type: ignore[type-abstract]
    doc_path = tmp_path / "notes.md"
    doc_path.write_text(
        "# Farm Notes\nIrrigation schedule for tomatoes and soil moisture checks.\n",
        encoding="utf-8",
    )
    doc = await km.ingest(doc_path)
    assert doc.status.value == "ready"
    hits = await km.search("tomatoes")
    assert hits
    summary = await km.summarize(doc.id)
    assert "tomato" in summary.lower() or "Irrigation" in summary or "Farm" in summary
