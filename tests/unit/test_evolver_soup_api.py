"""Unit tests for Evolver and SOUP REST API endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sage.api.app import create_app
from sage.core.engine import SageEngine


@pytest.mark.asyncio
async def test_evolver_and_soup_api(engine: SageEngine) -> None:
    app = create_app(engine)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. List variants (initial empty)
        r = await client.get("/api/v1/evolver/variants")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

        # 2. Propose variant
        r = await client.post(
            "/api/v1/evolver/variants",
            json={
                "name": "optimized-prompt",
                "payload": "Answer questions accurately and concisely.",
                "mutation_description": "Added conciseness directive",
                "mutation_target": "system_prompt",
            },
        )
        assert r.status_code == 200
        variant = r.json()
        assert variant["name"] == "optimized-prompt"
        assert variant["status"] == "candidate"
        variant_id = variant["id"]

        # 3. Retrieve variant
        r = await client.get(f"/api/v1/evolver/variants/{variant_id}")
        assert r.status_code == 200
        assert r.json()["id"] == variant_id

        # 4. Retrieve lineage
        r = await client.get(f"/api/v1/evolver/variants/{variant_id}/lineage")
        assert r.status_code == 200
        assert len(r.json()) >= 1

        # 5. Run SOUP comparison
        r = await client.post(
            "/api/v1/soup/compare",
            json={
                "name": "API Test Comparison",
                "variant_ids": [variant_id],
                "eval_set": [
                    {
                        "id": "c1",
                        "input": "test prompt",
                        "expected": "accurately concisely",
                    }
                ],
            },
        )
        assert r.status_code == 200
        report = r.json()
        assert report["run_id"]
        run_id = report["run_id"]

        # 6. Retrieve SOUP run
        r = await client.get(f"/api/v1/soup/runs/{run_id}")
        assert r.status_code == 200
        assert r.json()["id"] == run_id

        # 7. Retrieve SOUP trials
        r = await client.get(f"/api/v1/soup/runs/{run_id}/trials")
        assert r.status_code == 200
        assert len(r.json()) >= 1

        # 8. Retrieve SOUP trace
        r = await client.get(f"/api/v1/soup/runs/{run_id}/trace")
        assert r.status_code == 200
        trace = r.json()
        assert trace["run_id"] == run_id

        # 9. Apply variant with evidence and approval
        r = await client.post(
            f"/api/v1/evolver/variants/{variant_id}/apply",
            json={
                "approved": True,
                "approver": "tester",
                "reason": "Outperformed baseline in test",
                "run_id": run_id,
                "mean_score": 90.0,
                "baseline_mean_score": 50.0,
                "cases_evaluated": 1,
                "cases_won": 1,
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "active"

        # 10. Retire variant
        r = await client.post(f"/api/v1/evolver/variants/{variant_id}/retire")
        assert r.status_code == 200
        assert r.json()["status"] == "retired"
