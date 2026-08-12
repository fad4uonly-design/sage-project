from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from model_integration_engine.application.changes import (
    ChangeSetV3,
    FileChange,
    ReversibleApplicationManager,
)
from model_integration_engine.application.lifecycle import (
    Part3LifecycleConfig,
    Part3LifecycleEngine,
)
from model_integration_engine.application.vertical_slice import (
    Phase2VerticalSliceEngine,
    VerticalSliceConfig,
    default_target_profile,
    environment_info,
)
from model_integration_engine.approval.binding import ApprovalBindingService
from model_integration_engine.evidence import canonical_json_bytes, sha256_digest
from model_integration_engine.packaging.draft import DraftIntegrationPackageBuilder
from model_integration_engine.packaging.proposed import ImmutablePackageStore
from model_integration_engine.registry.capability_registry import (
    RegistryEligibilityError,
    ValidatedCapabilityRegistry,
)
from model_integration_engine.sandbox.artifacts import SecureArtifactResolver
from model_integration_engine.sandbox.contracts import (
    ArtifactDeclaration,
    CollectedArtifactCandidate,
)
from model_integration_engine.regression.framework import (
    RegressionFramework,
    RegressionPlanV3,
    RegressionState,
)

from tests.phase2_support import (
    DeterministicProbeBackend,
    FixtureTransport,
    fixed_clock,
    operation_context,
)

ENDPOINT = "http://fixture-ollama.invalid:11434"


def lifecycle(tmp_path):
    backend = DeterministicProbeBackend()
    phase2 = Phase2VerticalSliceEngine(
        FixtureTransport(), backend, DraftIntegrationPackageBuilder(), fixed_clock
    )
    collection = tmp_path / "sandbox-collection"
    collection.mkdir(parents=True, exist_ok=True)
    artifact_path = collection / "probe-attestation.json"
    artifact_path.write_text('{"fixture": true}', encoding="utf-8")
    artifact_digest = sha256_digest(artifact_path.read_bytes())
    declaration = ArtifactDeclaration(
        "probe-attestation", "probe-attestation.json", "application/json"
    )
    candidate = CollectedArtifactCandidate(
        "probe-attestation", "probe-attestation.json", "application/json",
        artifact_path.stat().st_size, artifact_digest, str(collection), "fixture-sandbox-run"
    )
    artifact_resolution = SecureArtifactResolver(tmp_path / "artifact-store").resolve(
        collection_root=collection,
        declarations=(declaration,),
        candidates=(candidate,),
        run_id="fixture-sandbox-run",
    )
    config = Part3LifecycleConfig(
        vertical_slice=VerticalSliceConfig(
            ENDPOINT,
            "example-model:4b",
            default_target_profile(),
            environment_info(
                environment_id="env:registry-fixture",
                locality="REMOTE",
                sandbox_backend_id=backend.backend_id,
            ),
            False,
        ),
        package_store_root=tmp_path / "packages",
        identity_ledger_path=tmp_path / "ledger.json",
        artifact_resolution=artifact_resolution,
    )
    result = asyncio.run(
        Part3LifecycleEngine(phase2, fixed_clock).run(config, operation_context())
    )
    store = ImmutablePackageStore(config.package_store_root)
    approval = ApprovalBindingService(store, fixed_clock)
    decision = approval.record_human_decision(
        result.approval_request,
        decision="APPROVED",
        actor_id="human:test",
        authentication_ref="audit:test",
        human_authority=True,
    )
    return result, store, approval, decision


def states(functional="PASS", capability="VALIDATED", compatibility="COMPATIBLE_WITH_ADAPTER", config="one", risks=None):
    return RegressionState(
        state_id=f"state:{functional}:{config}",
        functional={"smoke": functional},
        capabilities={
            "generation.text": {"validation": capability, "score": 1.0}
        },
        compatibility={"overall": compatibility},
        configuration={"model_binding": config},
        risks=risks or {},
    )


def plan(expected=("model_binding",)):
    return RegressionPlanV3(
        plan_id="regression:test",
        mandatory_checks=(
            "functional:smoke",
            "capability:generation.text",
            "compatibility:overall",
            "configuration:model_binding",
        ),
        expected_configuration_changes=expected,
        fail_closed=True,
    )


def test_regression_framework_passes_and_fails_closed() -> None:
    framework = RegressionFramework()
    passed = framework.compare(states(config="old"), states(config="new"), plan())
    assert passed.verdict == "PASS"
    assert passed.configuration_changes == ("model_binding",)

    failed = framework.compare(
        states(config="old"),
        states(functional="FAIL", capability="UNVALIDATED", compatibility="INCOMPATIBLE", config="new"),
        plan(),
    )
    assert failed.verdict == "FAIL"
    assert any(item.mandatory and item.outcome == "FAIL" for item in failed.findings)

    risk_failed = framework.compare(
        states(config="same"),
        states(config="same", risks={"new": {"blocking": True, "severity": "HIGH"}}),
        plan(expected=()),
    )
    assert risk_failed.verdict == "FAIL"
    assert risk_failed.new_risks == ("new",)


def approved_change_context(tmp_path):
    result, store, approval, decision = lifecycle(tmp_path)
    document = store.read(result.submitted_package)
    configuration = document["base_package"]["configuration"]["values"]
    content = canonical_json_bytes(configuration)
    change = FileChange(
        operation="ADD",
        relative_path="model-bindings/proposed.json",
        before_digest=None,
        after_content=content,
        after_digest=sha256_digest(content),
    )
    change_set = ChangeSetV3(
        change_set_id="change-set:proposed-model-binding",
        changes=(change,),
        context_paths=("capability-registry.json", "configuration.json"),
    )
    assert change_set.digest == document["change_set"]["digest"]
    return result, approval, decision, change_set


def test_post_application_regression_failure_restores_snapshot(tmp_path) -> None:
    result, approval, decision, change_set = approved_change_context(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "configuration.json").write_text("old-config", encoding="utf-8")
    (target / "capability-registry.json").write_text("old-registry", encoding="utf-8")
    framework = RegressionFramework()
    preflight = framework.compare(states(config="old"), states(config="new"), plan())
    post_failure = framework.compare(
        states(config="old"), states(functional="FAIL", config="new"), plan()
    )
    manager = ReversibleApplicationManager(
        target_root=target,
        snapshot_root=tmp_path / "snapshots",
        approval_service=approval,
    )
    application = manager.apply(
        change_set=change_set,
        submitted=result.submitted_package,
        approval_request=result.approval_request,
        approval_decision=decision,
        preflight=preflight,
        post_regression=lambda: post_failure,
    )
    assert application.outcome == "ROLLED_BACK"
    assert application.rollback_outcome == "PASS"
    assert not (target / "model-bindings/proposed.json").exists()
    assert (target / "configuration.json").read_text() == "old-config"
    assert (target / "capability-registry.json").read_text() == "old-registry"


def test_rollback_failure_is_visible_and_fails_closed(tmp_path) -> None:
    result, approval, decision, change_set = approved_change_context(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "configuration.json").write_text("old", encoding="utf-8")
    (target / "capability-registry.json").write_text("old", encoding="utf-8")
    framework = RegressionFramework()
    preflight = framework.compare(states(config="old"), states(config="new"), plan())
    post = framework.compare(states(config="old"), states(functional="FAIL", config="new"), plan())
    manager = ReversibleApplicationManager(
        target_root=target,
        snapshot_root=tmp_path / "snapshots",
        approval_service=approval,
        fail_restore_paths=frozenset({"model-bindings/proposed.json"}),
    )
    application = manager.apply(
        change_set=change_set,
        submitted=result.submitted_package,
        approval_request=result.approval_request,
        approval_decision=decision,
        preflight=preflight,
        post_regression=lambda: post,
    )
    assert application.outcome == "ROLLBACK_FAILED"
    assert application.rollback_outcome == "FAIL"


def registry_entry(result, validated=True):
    base = result.proposed_package.document["base_package"]
    composition = result.proposed_package.document["reconciled_identity"]
    text_claim = next(
        item for item in base["capabilities"] if item["capability_key"] == "generation.text"
    )
    evidence_id = next(
        item for item in text_claim["evidence_ids"]
        if any(ev["evidence_id"] == item and ev["level"] == "VALIDATED_BY_TEST" for ev in base["evidence"])
    )
    evidence_digest = sha256_digest({"evidence_id": evidence_id})
    artifact = base["artifacts"][0]
    subject = lambda kind, sid, version, digest: {
        "kind": kind, "subject_id": sid, "version": version, "digest": digest
    }
    return {
        "registration_id": "registration:part3-example",
        "status": "ACTIVE",
        "registered_at": "2026-08-10T10:00:00Z",
        "registered_by": "human:test",
        "composition": {
            "model": subject("MODEL", base["model"]["model_id"], None, artifact["digest"]),
            "artifact": subject("ARTIFACT", artifact["artifact_id"], None, artifact["digest"]),
            "runtime": subject("RUNTIME", base["runtime"]["runtime_id"], base["runtime"]["version"], sha256_digest("runtime-registry")),
            "deployment": subject("DEPLOYMENT", base["runtime"]["deployment_id"], None, composition["composition_digest"]),
            "adapter": subject("ADAPTER", base["adapter"]["adapter_id"], base["adapter"]["version"], base["adapter"]["source_manifest_digest"]),
            "configuration_digest": base["adapter"]["configuration_digest"],
            "environment_constraints": {"environment_id": "env:registry-fixture"},
        },
        "integration_package": {
            "package_id": result.submitted_package.package_id,
            "package_digest": result.submitted_package.package_digest,
            "schema_version": "0.3.0",
            "approval_event_ref": "approval:test",
            "post_application_regression_id": "regression:post",
            "post_application_regression_outcome": "PASS",
        },
        "capabilities": [
            {
                "claim_id": text_claim["claim_id"],
                "capability_key": "generation.text",
                "capability_class": "INTEGRATION_CAPABILITY",
                "subject_id": base["runtime"]["deployment_id"],
                "support": "SUPPORTED",
                "validation": "VALIDATED" if validated else "UNVALIDATED",
                "evidence_levels": ["VALIDATED_BY_TEST"],
                "evidence": [
                    {
                        "evidence_id": evidence_id,
                        "evidence_digest": evidence_digest,
                        "test_run_id": "fixture-sandbox-run",
                        "suite_id": "mie.safe-vertical-slice",
                        "suite_version": "0.2.0",
                        "outcome": "PASS",
                    }
                ],
                "parameters": {},
                "limitations": ["Registered composition only"],
                "validated_at": "2026-08-10T09:59:00Z",
            }
        ],
        "health": {
            "status": "HEALTHY",
            "checked_at": "2026-08-10T09:59:30Z",
            "check_id": "health:test",
            "evidence_id": evidence_id,
        },
        "rollback_ref": "rollback-plan:remove-proposed-binding",
        "disabled_at": None,
        "disable_reason": None,
    }


def test_registry_accepts_only_approved_regression_validated_capability(tmp_path) -> None:
    result, store, approval, decision = lifecycle(tmp_path)
    regression = RegressionFramework().compare(states(config="same"), states(config="same"), plan(expected=()))
    registry = ValidatedCapabilityRegistry(tmp_path / "registry.json", approval)
    update = registry.register(
        entry=registry_entry(result, validated=True),
        submitted=result.submitted_package,
        approval_request=result.approval_request,
        approval_decision=decision,
        post_regression=regression,
    )
    assert update.registry_version == "1"
    assert registry.snapshot()["entries"][0]["capabilities"][0]["validation"] == "VALIDATED"


def test_registry_rejects_unvalidated_or_failed_regression(tmp_path) -> None:
    result, store, approval, decision = lifecycle(tmp_path)
    registry = ValidatedCapabilityRegistry(tmp_path / "registry.json", approval)
    passed = RegressionFramework().compare(states(config="same"), states(config="same"), plan(expected=()))
    with pytest.raises(RegistryEligibilityError) as error:
        registry.register(
            entry=registry_entry(result, validated=False),
            submitted=result.submitted_package,
            approval_request=result.approval_request,
            approval_decision=decision,
            post_regression=passed,
        )
    assert error.value.code == "REGISTRY_CAPABILITY_UNVALIDATED"

    failed = RegressionFramework().compare(states(), states(functional="FAIL"), plan(expected=()))
    with pytest.raises(RegistryEligibilityError) as error:
        registry.register(
            entry=registry_entry(result, validated=True),
            submitted=result.submitted_package,
            approval_request=result.approval_request,
            approval_decision=decision,
            post_regression=failed,
        )
    assert error.value.code == "REGISTRY_REGRESSION_FAILED"
