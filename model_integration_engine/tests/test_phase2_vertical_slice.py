from __future__ import annotations

import asyncio
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from model_integration_engine.application.vertical_slice import (
    Phase2VerticalSliceEngine,
    VerticalSliceConfig,
    default_target_profile,
    environment_info,
)
from model_integration_engine.packaging.draft import DraftIntegrationPackageBuilder

from tests.phase2_support import (
    DeterministicProbeBackend,
    FixtureTransport,
    fixed_clock,
    load_fixture,
    operation_context,
)

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "http://fixture-ollama.invalid:11434"


def execute(transport, model_reference):
    backend = DeterministicProbeBackend()
    engine = Phase2VerticalSliceEngine(
        transport=transport,
        probe_backend=backend,
        package_builder=DraftIntegrationPackageBuilder(),
        clock=fixed_clock,
    )
    config = VerticalSliceConfig(
        endpoint=ENDPOINT,
        model_reference=model_reference,
        target_profile=default_target_profile(),
        environment=environment_info(
            environment_id="env:fixture",
            locality="REMOTE",
            sandbox_backend_id=backend.backend_id,
            attributes={
                "fixture": True,
                "resource_limits": {
                    "timeout_seconds": 60,
                    "memory_bytes": 536870912,
                },
            },
        ),
        live_validation=False,
    )
    return asyncio.run(engine.run(config, operation_context()))


def test_vertical_slice_generates_schema_valid_draft_and_stops_at_approval() -> None:
    result = execute(FixtureTransport(), "example-model:4b")

    assert result.state == "DRAFT_PENDING_APPROVAL"
    assert result.problem is None
    assert result.package is not None
    document = result.package.document
    assert document["package_state"] == "DRAFT"
    assert document["approval"]["state"] == "NOT_REQUESTED"
    assert document["configuration"]["values"]["lifecycle_state"] == "DRAFT_PENDING_APPROVAL"
    assert document["configuration"]["contains_secrets"] is False
    assert document["provenance"]["contains_credentials"] is False
    assert document["regression"]["preflight_outcome"] == "NOT_RUN"
    assert document["runtime"]["kind"] == "ollama"
    assert document["artifacts"][0]["digest"] == "sha256:" + "a" * 64
    assert document["evaluations"][0]["verdict"] == "PASS"
    assert document["proposed_changes"][0]["reversible"] is True
    assert not any(key in document for key in ("registration", "applied_changes"))

    schema = json.loads(
        (ROOT / "schemas" / "integration-package.schema.json").read_text()
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def test_evidence_and_capability_examples_are_deployment_scoped() -> None:
    result = execute(FixtureTransport(), "example-model:4b")
    document = result.package.document

    basic_evidence = next(
        item
        for item in document["evidence"]
        if item["observation_key"] == "probe.basic_generation"
    )
    text_capability = next(
        item
        for item in document["capabilities"]
        if item["capability_key"] == "generation.text"
    )
    assert basic_evidence["level"] == "VALIDATED_BY_TEST"
    assert basic_evidence["outcome"] == "PASS"
    assert basic_evidence["environment_id"] == "env:fixture"
    assert basic_evidence["subject"]["kind"] == "DEPLOYMENT"
    assert text_capability["validation"] == "VALIDATED"
    assert text_capability["subject"]["kind"] == "DEPLOYMENT"
    assert text_capability["parameters"]["adapter_id"] == "mie.adapter.ollama-chat"
    assert text_capability["parameters"]["environment_id"] == "env:fixture"


def test_compatibility_example_has_explicit_reasons_and_evidence() -> None:
    result = execute(FixtureTransport(), "example-model:4b")
    compatibility = result.package.document["compatibility"]

    assert compatibility["status"] == "COMPATIBLE_WITH_ADAPTER"
    mandatory = [item for item in compatibility["requirements"] if item["mandatory"]]
    assert all(item["status"] == "SATISFIED_WITH_ADAPTER" for item in mandatory)
    assert all(item["evidence_ids"] for item in mandatory)
    assert compatibility["blockers"] == []
    assert compatibility["unknowns"] == []


def test_empty_model_list_stops_without_package() -> None:
    result = execute(FixtureTransport(tags={"models": []}), None)

    assert result.package is None
    assert result.problem is not None
    assert result.problem.code == "NO_MODELS_DISCOVERED"


def test_qwen_fixture_uses_same_generic_path_and_adapter() -> None:
    transport = FixtureTransport(
        tags=load_fixture("qwen-tags.json"),
        show=load_fixture("qwen-show.json"),
    )
    result = execute(transport, "qwen3:4b")

    assert result.state == "DRAFT_PENDING_APPROVAL"
    assert result.package is not None
    document = result.package.document
    assert document["runtime"]["model_reference"] == "qwen3:4b"
    assert document["adapter"]["adapter_id"] == "mie.adapter.ollama-chat"
    assert document["package_state"] == "DRAFT"
    production_source = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (ROOT / "src").rglob("*.py")
    )
    assert "qwen" not in production_source
