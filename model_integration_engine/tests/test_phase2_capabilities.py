from __future__ import annotations

import asyncio

from model_integration_engine.capabilities.hypotheses import (
    GenericCapabilityHypothesisDetector,
)
from model_integration_engine.domain import (
    EvidenceLevel,
    SupportState,
    ValidationState,
)
from model_integration_engine.plugins.ollama.client import OllamaClient
from model_integration_engine.plugins.ollama.discovery import OllamaDiscoveryProvider
from model_integration_engine.plugins.ollama.inspection import OllamaModelInspector

from tests.phase2_support import FixtureTransport, fixed_clock

ENDPOINT = "http://fixture-ollama.invalid:11434"


def hypotheses(show=None):
    async def operation():
        transport = FixtureTransport(show=show) if show is not None else FixtureTransport()
        client = OllamaClient(ENDPOINT, transport)
        discovery = await OllamaDiscoveryProvider(client, clock=fixed_clock).discover_all()
        inspection = await OllamaModelInspector(client, clock=fixed_clock).inspect_model(
            discovery.models[0]
        )
        result = GenericCapabilityHypothesisDetector(clock=fixed_clock).detect(
            runtime=discovery.runtime,
            model=discovery.models[0],
            inspection=inspection,
            available_evidence=discovery.evidence + inspection.evidence,
        )
        return result

    return asyncio.run(operation())


def test_capability_hypotheses_preserve_validation_boundary() -> None:
    result = hypotheses()
    by_key = {claim.capability_key: claim for claim in result.claims}

    assert {
        "generation.text",
        "instruction.following",
        "reasoning.general",
        "output.schema_constrained",
        "tools.function_calling",
        "modality.vision.input",
        "generation.embeddings",
        "protocol.streaming",
        "context.long",
    }.issubset(by_key)
    assert by_key["generation.text"].support is SupportState.SUPPORTED
    assert by_key["generation.text"].validation is ValidationState.UNVALIDATED
    assert by_key["tools.function_calling"].validation is ValidationState.UNVALIDATED
    assert by_key["reasoning.general"].support is SupportState.UNKNOWN
    assert by_key["output.schema_constrained"].support is SupportState.UNKNOWN
    assert by_key["protocol.streaming"].support is SupportState.UNKNOWN
    assert by_key["context.long"].support is SupportState.SUPPORTED
    assert by_key["context.long"].validation is ValidationState.UNVALIDATED
    assert all(claim.evidence_ids for claim in result.claims)


def test_absent_declaration_is_unknown_not_unsupported() -> None:
    result = hypotheses(show={"details": {}, "model_info": {}, "capabilities": []})

    assert all(claim.support is not SupportState.NOT_SUPPORTED for claim in result.claims)
    vision = next(
        claim for claim in result.claims if claim.capability_key == "modality.vision.input"
    )
    assert vision.support is SupportState.UNKNOWN
    assert EvidenceLevel.INFERRED in vision.evidence_levels
