from __future__ import annotations

import asyncio

from model_integration_engine.domain import Completeness
from model_integration_engine.plugins.ollama.client import OllamaClient
from model_integration_engine.plugins.ollama.discovery import OllamaDiscoveryProvider

from tests.phase2_support import FixtureTransport, fixed_clock

ENDPOINT = "http://fixture-ollama.invalid:11434"


def discover(transport: FixtureTransport):
    client = OllamaClient(ENDPOINT, transport)
    return asyncio.run(OllamaDiscoveryProvider(client, clock=fixed_clock).discover_all())


def test_ollama_discovery_normalization_is_deterministic_and_content_bound() -> None:
    first = discover(FixtureTransport())
    second = discover(FixtureTransport())

    assert first.completeness is Completeness.COMPLETE
    assert first.runtime is not None
    assert first.runtime.kind == "ollama"
    assert first.runtime.version == "0.12.6"
    assert len(first.models) == 1
    model = first.models[0]
    assert model.runtime_reference == "example-model:4b"
    assert model.content_digest == "sha256:" + "a" * 64
    assert model.identity_status == "CONTENT_ADDRESSED"
    assert model.artifact_subject is not None
    assert model.raw_summary["fixture_extension"] == {"preserved": True}
    assert model.model_subject == second.models[0].model_subject
    assert model.deployment_subject == second.models[0].deployment_subject
    assert [item.evidence_id for item in first.evidence] == [
        item.evidence_id for item in second.evidence
    ]


def test_missing_runtime_is_structured_and_recoverable() -> None:
    result = discover(FixtureTransport(unavailable=True))

    assert result.runtime is None
    assert result.models == ()
    assert result.completeness is Completeness.FAILED
    assert result.problem is not None
    assert result.problem.code == "RUNTIME_UNREACHABLE"
    assert result.problem.retryable is True


def test_empty_model_list_is_a_valid_discovery_result() -> None:
    result = discover(FixtureTransport(tags={"models": []}))

    assert result.runtime is not None
    assert result.models == ()
    assert result.completeness is Completeness.COMPLETE
    assert result.problem is None
    list_evidence = [
        item for item in result.evidence if item.observation_key == "runtime.model_list"
    ]
    assert list_evidence[0].observed_value == {"count": 0}


def test_malformed_version_response_does_not_crash_engine() -> None:
    result = discover(FixtureTransport(version={"not_version": 1}))

    assert result.problem is not None
    assert result.problem.code == "MALFORMED_VERSION_RESPONSE"
    assert result.completeness is Completeness.FAILED


def test_malformed_model_list_is_reported_without_invention() -> None:
    result = discover(FixtureTransport(tags={"models": {"wrong": "shape"}}))

    assert result.runtime is not None
    assert result.problem is not None
    assert result.problem.code == "MALFORMED_MODEL_LIST"
    assert result.models == ()


def test_model_without_digest_remains_provisional_not_tag_identified() -> None:
    transport = FixtureTransport()
    del transport.tags_value["models"][0]["digest"]
    result = discover(transport)

    model = result.models[0]
    assert model.content_digest is None
    assert model.artifact_subject is None
    assert model.identity_status == "PROVISIONAL"
    assert model.deployment_subject.digest is not None
