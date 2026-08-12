from __future__ import annotations

import asyncio

from model_integration_engine.application.vertical_slice import (
    Phase2VerticalSliceEngine,
    VerticalSliceConfig,
    default_target_profile,
    environment_info,
)
from model_integration_engine.domain import SupportState, ValidationState
from model_integration_engine.packaging.draft import DraftIntegrationPackageBuilder

from tests.phase2_support import (
    DeterministicProbeBackend,
    FixtureTransport,
    MissingControlsProbeBackend,
    fixed_clock,
    operation_context,
)

ENDPOINT = "http://fixture-ollama.invalid:11434"


def run_engine(transport, backend):
    engine = Phase2VerticalSliceEngine(
        transport=transport,
        probe_backend=backend,
        package_builder=DraftIntegrationPackageBuilder(),
        clock=fixed_clock,
    )
    config = VerticalSliceConfig(
        endpoint=ENDPOINT,
        model_reference="example-model:4b",
        target_profile=default_target_profile(),
        environment=environment_info(
            environment_id="env:fixture",
            locality="REMOTE",
            sandbox_backend_id=backend.backend_id,
            attributes={"resource_limits": {"timeout_seconds": 60}},
        ),
        live_validation=False,
    )
    return asyncio.run(engine.run(config, operation_context()))


def test_probe_failure_is_evidence_and_does_not_abort_other_probes() -> None:
    result = run_engine(
        FixtureTransport(fail_prompt_markers=("alpha-29",)),
        DeterministicProbeBackend(),
    )

    assert result.package is not None
    assert result.probes is not None
    outcomes = {item.raw.kind.value: item.raw.outcome.value for item in result.probes.results}
    assert outcomes["INSTRUCTION_FOLLOWING"] == "ERROR"
    assert outcomes["BASIC_GENERATION"] == "PASS"
    instruction = next(
        claim
        for claim in result.probes.claims
        if claim.capability_key == "instruction.following"
    )
    assert instruction.validation is ValidationState.FAILED
    assert instruction.support is SupportState.UNKNOWN
    probe_evidence = next(
        evidence
        for evidence in result.probes.evidence
        if evidence.observation_key == "probe.instruction_following"
    )
    assert probe_evidence.outcome.value == "ERROR"
    assert probe_evidence.environment_id == "env:fixture"


def test_missing_isolation_controls_block_probe_promotion() -> None:
    result = run_engine(FixtureTransport(), MissingControlsProbeBackend())

    assert result.probes is not None
    assert result.probes.problem is not None
    assert result.probes.problem.code == "SANDBOX_CONTROL_UNAVAILABLE"
    assert result.probes.results == ()
    assert result.package is not None
    assert any(risk["blocking"] for risk in result.package.document["risks"])
