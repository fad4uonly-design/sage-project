"""Knowledge graph tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sage.core.engine import SageEngine
from sage.knowledge.graph.interfaces import KnowledgeGraph
from sage.knowledge.graph.models import Entity, EntityType, RelationType
from sage.knowledge.interfaces import KnowledgeManager


@pytest.mark.asyncio
async def test_seed_ontology_loaded(engine: SageEngine) -> None:
    kg = engine.container.resolve(KnowledgeGraph)  # type: ignore[type-abstract]
    stats = await kg.stats()
    assert stats["entities"] >= 5
    assert stats["edges"] >= 3
    tomato = await kg.find_entity("Tomato")
    assert tomato is not None


@pytest.mark.asyncio
async def test_upsert_and_link(engine: SageEngine) -> None:
    kg = engine.container.resolve(KnowledgeGraph)  # type: ignore[type-abstract]
    a = await kg.upsert_entity(
        Entity(name="Pepper", entity_type=EntityType.CROP, confidence=0.8)
    )
    b = await kg.upsert_entity(
        Entity(name="Warm Climate", entity_type=EntityType.CONDITION, confidence=0.7)
    )
    edge = await kg.link(a, RelationType.GROWS_IN.value, b, confidence=0.8)
    assert edge.relation == RelationType.GROWS_IN.value
    triples = await kg.neighbors(a.id, relation=RelationType.GROWS_IN.value)
    assert any(t.object.name.lower().startswith("warm") for t in triples)


@pytest.mark.asyncio
async def test_extract_and_merge(engine: SageEngine) -> None:
    kg = engine.container.resolve(KnowledgeGraph)  # type: ignore[type-abstract]
    result = await kg.extract_and_merge(
        "Wheat is a crop. Wheat requires water. Wheat is affected by drought.",
        source="test",
    )
    assert len(result.entities) >= 2
    assert len(result.edges) >= 2
    facts = await kg.query_relation(subject="Wheat", relation=RelationType.REQUIRES.value)
    assert facts


@pytest.mark.asyncio
async def test_ingest_populates_graph(engine: SageEngine, tmp_path: Path) -> None:
    km = engine.container.resolve(KnowledgeManager)  # type: ignore[type-abstract]
    kg = engine.container.resolve(KnowledgeGraph)  # type: ignore[type-abstract]
    path = tmp_path / "agri.md"
    path.write_text(
        "Corn is a crop. Corn requires fertilizer. Corn grows in warm climate.\n",
        encoding="utf-8",
    )
    before = await kg.stats()
    await km.ingest(path, category="agriculture")
    after = await kg.stats()
    assert after["entities"] >= before["entities"]
    corn = await kg.find_entity("Corn")
    assert corn is not None


@pytest.mark.asyncio
async def test_path_finding(engine: SageEngine) -> None:
    kg = engine.container.resolve(KnowledgeGraph)  # type: ignore[type-abstract]
    tomato = await kg.find_entity("Tomato")
    water = await kg.find_entity("Water")
    if tomato and water:
        path = await kg.path(tomato.id, water.id, max_depth=3)
        # Seed links tomato requires water — path should exist
        assert path is not None
        assert len(path.nodes) >= 2
