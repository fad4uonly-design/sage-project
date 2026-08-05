"""Knowledge Discovery + API app tests (v0.6.0)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from sage.api.app import create_app
from sage.core.engine import SageEngine
from sage.discovery.engine import DiscoveryEngine


@pytest.mark.asyncio
async def test_discovery_engine(engine: SageEngine) -> None:
    disc = engine.container.resolve(DiscoveryEngine)  # type: ignore[type-abstract]
    insights = await disc.discover(limit=10)
    assert isinstance(insights, list)
    # Graph seed should yield at least pattern / hub / relation insights
    assert len(insights) >= 1
    recent = await disc.list_recent(limit=5)
    assert len(recent) >= 1


@pytest.mark.asyncio
async def test_api_status_and_ask(engine: SageEngine) -> None:
    app = create_app(engine)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/status")
        assert r.status_code == 200
        data = r.json()
        assert data["version"]
        assert "modules" in data
        assert "discovery" in data["modules"] or "context" in data["modules"]

        r2 = await client.post("/api/v1/ask", json={"message": "status"})
        assert r2.status_code == 200
        assert "reply" in r2.json()

        r3 = await client.get("/api/v1/context")
        assert r3.status_code == 200
        assert "summary" in r3.json()

        r4 = await client.get("/api/v1/workflows")
        assert r4.status_code == 200
        assert isinstance(r4.json(), list)

        r5 = await client.post("/api/v1/discovery/run")
        assert r5.status_code == 200
        assert isinstance(r5.json(), list)

        r6 = await client.get("/")
        assert r6.status_code == 200
        assert "SAGE" in r6.text


@pytest.mark.asyncio
async def test_api_projects_goals(engine: SageEngine) -> None:
    app = create_app(engine)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        p = await client.post(
            "/api/v1/projects",
            json={"name": "Dashboard Demo", "description": "UX test", "activate": True},
        )
        assert p.status_code == 200
        assert p.json()["name"] == "Dashboard Demo"

        g = await client.post(
            "/api/v1/goals",
            json={"title": "Ship web UI", "horizon": "medium"},
        )
        assert g.status_code == 200
        assert g.json()["title"] == "Ship web UI"

        plist = await client.get("/api/v1/projects")
        assert any(x["name"] == "Dashboard Demo" for x in plist.json())
