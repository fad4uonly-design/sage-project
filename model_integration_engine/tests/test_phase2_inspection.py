from __future__ import annotations

import asyncio

from model_integration_engine.domain import EvidenceKind, EvidenceLevel
from model_integration_engine.plugins.ollama.client import OllamaClient
from model_integration_engine.plugins.ollama.discovery import OllamaDiscoveryProvider
from model_integration_engine.plugins.ollama.inspection import OllamaModelInspector

from tests.phase2_support import FixtureTransport, fixed_clock

ENDPOINT = "http://fixture-ollama.invalid:11434"


def inspect_with(transport: FixtureTransport):
    async def operation():
        client = OllamaClient(ENDPOINT, transport)
        discovery = await OllamaDiscoveryProvider(client, clock=fixed_clock).discover_all()
        inspection = await OllamaModelInspector(client, clock=fixed_clock).inspect_model(
            discovery.models[0]
        )
        return discovery, inspection

    return asyncio.run(operation())


def test_model_detail_parsing_separates_facts_and_derived_values() -> None:
    _, inspection = inspect_with(FixtureTransport())

    assert inspection.details is not None
    assert inspection.details.architecture == "generic_transformer"
    assert inspection.details.context_length == 65536
    assert inspection.details.tokenizer_model == "gpt2"
    assert inspection.details.parameter_count_estimate == 4_020_000_000
    assert inspection.details.declared_capabilities == (
        "completion",
        "thinking",
        "tools",
    )
    architecture = next(
        item
        for item in inspection.evidence
        if item.observation_key == "general.architecture"
    )
    assert architecture.kind is EvidenceKind.METADATA_FIELD
    assert architecture.level is EvidenceLevel.DETECTED_FROM_METADATA
    derived = next(
        item
        for item in inspection.evidence
        if item.observation_key == "derived.parameter_count_estimate"
    )
    assert derived.kind is EvidenceKind.DERIVATION
    assert derived.level is EvidenceLevel.INFERRED
    assert derived.derived_from


def test_missing_metadata_remains_unknown() -> None:
    show = {
        "details": {"format": "gguf"},
        "capabilities": [],
    }
    _, inspection = inspect_with(FixtureTransport(show=show))

    assert inspection.details is not None
    assert inspection.details.architecture is None
    assert inspection.details.context_length is None
    assert inspection.details.tokenizer_model is None
    assert "architecture" in inspection.details.unknowns
    assert "context_length" in inspection.details.unknowns
    assert not any(
        item.level is EvidenceLevel.NOT_SUPPORTED for item in inspection.evidence
    )


def test_inspection_evidence_preserves_source_provenance() -> None:
    _, inspection = inspect_with(FixtureTransport())
    item = next(
        evidence
        for evidence in inspection.evidence
        if evidence.observation_key == "tokenizer.ggml.model"
    )

    assert item.source.uri == ENDPOINT + "/api/show"
    assert item.source.digest == inspection.details.raw_response_digest
    assert item.source.locator == "/tokenizer/ggml/model"
    assert item.collector_id == "mie.inspector.ollama-model-details"
