from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from model_integration_engine.adapters.engine import (
    AdapterCatalog,
    AdapterRequirement,
    AdapterResolutionDisposition,
    GenericAdapterEngine,
    generic_ollama_adapter_spec,
)
from model_integration_engine.application.vertical_slice import (
    Phase2VerticalSliceEngine,
    VerticalSliceConfig,
    default_target_profile,
    environment_info,
)
from model_integration_engine.domain import SubjectKind, SubjectRef, TrustState
from model_integration_engine.evidence import sha256_digest
from model_integration_engine.identity.reconciliation import (
    IdentityInputs,
    IdentityLedger,
    ModelIdentityReconciler,
)
from model_integration_engine.packaging.draft import DraftIntegrationPackageBuilder
from model_integration_engine.runtimes.ollama import OllamaRuntimePlugin
from model_integration_engine.runtimes.registry import (
    RuntimePluginError,
    RuntimePluginRegistry,
)
from model_integration_engine.sandbox.contracts import IsolationClass, SandboxOutcome

from tests.phase2_support import (
    DeterministicProbeBackend,
    FixtureTransport,
    fixed_clock,
    operation_context,
)

ENDPOINT = "http://fixture-ollama.invalid:11434"


def test_runtime_plugin_registry_is_generic_and_deterministic() -> None:
    plugin = OllamaRuntimePlugin(FixtureTransport())
    registry = RuntimePluginRegistry()
    registry.register(plugin)
    selected = registry.select(ENDPOINT, runtime_kind="ollama")
    assert selected.descriptor_v3.runtime_kind == "ollama"
    assert "ollama-native-http" in selected.descriptor_v3.protocols
    with pytest.raises(RuntimePluginError) as duplicate:
        registry.register(plugin)
    assert duplicate.value.code == "RUNTIME_PLUGIN_DUPLICATE"
    with pytest.raises(RuntimePluginError) as missing:
        registry.select("process://local", runtime_kind="process")
    assert missing.value.code == "RUNTIME_PLUGIN_NOT_FOUND"


def identity_inputs(content: str, environment: str, evidence=("ev-1",)):
    artifact = SubjectRef(
        SubjectKind.ARTIFACT, "artifact:" + content[-4:], digest=content
    )
    runtime = SubjectRef(
        SubjectKind.RUNTIME, "runtime:test", version="1", digest=sha256_digest("runtime")
    )
    deployment = SubjectRef(
        SubjectKind.DEPLOYMENT, "deployment:tag", digest=sha256_digest({"content": content})
    )
    adapter = SubjectRef(
        SubjectKind.ADAPTER, "adapter:test", version="1", digest=sha256_digest("adapter")
    )
    return IdentityInputs(
        runtime=runtime,
        runtime_kind="fixture-runtime",
        runtime_model_reference="mutable:tag",
        artifact=artifact,
        deployment=deployment,
        adapter=adapter,
        configuration_digest=sha256_digest("config"),
        environment_digest=environment,
        model_metadata={"general.name": "Generic", "general.architecture": "unknown"},
        evidence_ids=evidence,
    )


def test_identity_reconciliation_detects_alias_collision_without_merging(tmp_path) -> None:
    ledger = IdentityLedger(tmp_path / "identity-ledger.json")
    reconciler = ModelIdentityReconciler(ledger=ledger, clock=fixed_clock)
    first = reconciler.reconcile(identity_inputs("sha256:" + "a" * 64, sha256_digest("env")))
    second = reconciler.reconcile(identity_inputs("sha256:" + "b" * 64, sha256_digest("env")))
    assert first.logical_model.subject_id != second.logical_model.subject_id
    assert second.alias_collision is True
    assert second.identity_status == "ALIAS_COLLISION_DETECTED"
    assert first.deployment.digest != second.deployment.digest


def test_identity_logical_content_is_stable_but_composition_scopes_environment(tmp_path) -> None:
    reconciler = ModelIdentityReconciler(
        ledger=IdentityLedger(tmp_path / "ledger.json"), clock=fixed_clock
    )
    content = "sha256:" + "c" * 64
    first = reconciler.reconcile(identity_inputs(content, sha256_digest("env-one")))
    second = reconciler.reconcile(identity_inputs(content, sha256_digest("env-two")))
    assert first.logical_model == second.logical_model
    assert first.composition.digest != second.composition.digest
    assert first.evidence[0].derived_from == ("ev-1",)


def test_adapter_engine_reuses_configuration_before_generation() -> None:
    catalog = AdapterCatalog()
    catalog.register(generic_ollama_adapter_spec())
    engine = GenericAdapterEngine(catalog)
    requirement = AdapterRequirement(
        runtime_kind="ollama",
        contract_version="normalized-inference-0.1.0",
        operations=frozenset({"chat", "stream"}),
        deployment_id="deployment:test",
        runtime_endpoint=ENDPOINT,
        configuration={"runtime_owns_template": True},
        allowed_permissions=frozenset({"network:configured-runtime-endpoint"}),
    )
    result = engine.resolve(requirement)
    assert result.disposition is AdapterResolutionDisposition.CONFIGURE
    assert result.adapter.adapter_id == "mie.adapter.ollama-chat"
    assert result.configuration_digest.startswith("sha256:")
    assert result.accepted is True


def test_missing_adapter_produces_untrusted_non_executable_proposal() -> None:
    engine = GenericAdapterEngine(AdapterCatalog())
    result = engine.resolve(
        AdapterRequirement(
            runtime_kind="future-runtime",
            contract_version="normalized-inference-0.1.0",
            operations=frozenset({"chat"}),
            deployment_id="deployment:future",
            runtime_endpoint="process://future",
            configuration={},
            allowed_permissions=frozenset(),
        )
    )
    assert result.disposition is AdapterResolutionDisposition.GENERATE_PROPOSAL
    assert result.generated_proposal.trust_state is TrustState.UNTRUSTED_GENERATED
    assert result.generated_proposal.manifest["executable"] is False
    assert result.accepted is False

    class ReferenceResult:
        isolation_class = IsolationClass.REFERENCE_NOT_SECURITY_BOUNDARY
        security_boundary_claimed = False
        outcome = SandboxOutcome.PASS
        missing_controls = frozenset()
        cleanup_complete = True

    assert (
        engine.validate_generated_proposal(
            result.generated_proposal,
            ReferenceResult(),
            result.generated_proposal.artifact_digest,
        )
        is False
    )


def test_context_and_multimodal_capabilities_require_passing_probes(tmp_path) -> None:
    show = FixtureTransport().show_value
    show["capabilities"].append("vision")
    transport = FixtureTransport(show=show)
    backend = DeterministicProbeBackend()
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
        ),
        live_validation=False,
    )
    result = asyncio.run(engine.run(config, operation_context()))
    claims = {item.capability_key: item for item in result.probes.claims}
    assert claims["context.long"].validation.value == "UNVALIDATED"
    assert claims["context.handling"].validation.value == "VALIDATED"
    assert claims["modality.vision.input"].validation.value == "VALIDATED"
    assert any(
        item.observation_key == "probe.context_handling"
        and item.level.value == "VALIDATED_BY_TEST"
        for item in result.probes.evidence
    )
