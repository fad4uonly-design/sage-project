"""Opt-in read-only live Ollama discovery/inspection check.

Run only with both environment variables set:

    MIE_LIVE_OLLAMA_ENDPOINT=http://host:11434
    MIE_LIVE_OLLAMA_MODEL=<exact runtime reference>

This test never pulls, creates, copies, deletes, or registers a model. Probe
execution is excluded until a real sandbox backend is configured.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from model_integration_engine.plugins.ollama.client import (
    OllamaClient,
    StdlibJsonTransport,
)
from model_integration_engine.plugins.ollama.discovery import OllamaDiscoveryProvider
from model_integration_engine.plugins.ollama.inspection import OllamaModelInspector

ENDPOINT = os.environ.get("MIE_LIVE_OLLAMA_ENDPOINT")
MODEL = os.environ.get("MIE_LIVE_OLLAMA_MODEL")

pytestmark = pytest.mark.skipif(
    not ENDPOINT or not MODEL,
    reason="opt-in live Ollama endpoint/model not configured",
)


def test_live_read_only_discovery_and_inspection() -> None:
    async def operation():
        client = OllamaClient(ENDPOINT, StdlibJsonTransport(), timeout_seconds=15)
        discovery = await OllamaDiscoveryProvider(client).discover_all()
        matches = [item for item in discovery.models if item.runtime_reference == MODEL]
        assert discovery.runtime is not None
        assert discovery.problem is None
        assert len(matches) == 1
        inspection = await OllamaModelInspector(client).inspect_model(matches[0])
        assert inspection.problem is None
        assert inspection.details is not None
        return discovery, inspection

    discovery, inspection = asyncio.run(operation())
    assert discovery.models
    assert inspection.evidence
