from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

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
from model_integration_engine.packaging.draft import DraftIntegrationPackageBuilder
from model_integration_engine.packaging.proposed import ImmutablePackageStore

from tests.phase2_support import (
    DeterministicProbeBackend,
    FixtureTransport,
    fixed_clock,
    operation_context,
)

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "http://fixture-ollama.invalid:11434"


def run_lifecycle(tmp_path):
    backend = DeterministicProbeBackend()
    phase2 = Phase2VerticalSliceEngine(
        transport=FixtureTransport(),
        probe_backend=backend,
        package_builder=DraftIntegrationPackageBuilder(),
        clock=fixed_clock,
    )
    engine = Part3LifecycleEngine(phase2=phase2, clock=fixed_clock)
    config = Part3LifecycleConfig(
        vertical_slice=VerticalSliceConfig(
            endpoint=ENDPOINT,
            model_reference="example-model:4b",
            target_profile=default_target_profile(),
            environment=environment_info(
                environment_id="env:part3-fixture",
                locality="REMOTE",
                sandbox_backend_id=backend.backend_id,
                attributes={"fixture": True},
            ),
            live_validation=False,
        ),
        package_store_root=tmp_path / "packages",
        identity_ledger_path=tmp_path / "identity-ledger.json",
    )
    return asyncio.run(engine.run(config, operation_context())), config


def test_end_to_end_workflow_submits_immutable_package_then_stops(tmp_path) -> None:
    result, config = run_lifecycle(tmp_path)

    assert result.state == "DRAFT_PENDING_APPROVAL"
    assert result.problem is None
    assert result.submitted_package is not None
    assert result.approval_request is not None
    assert result.approval_request.state == "PENDING_HUMAN_APPROVAL"
    assert result.security.verdict == "BLOCKED"
    assert any(
        item.finding_id == "artifact-manifest-missing"
        for item in result.security.findings
    )
    store = ImmutablePackageStore(config.package_store_root)
    assert store.verify(result.submitted_package)
    document = store.read(result.submitted_package)
    assert document["lifecycle_state"] == "DRAFT_PENDING_APPROVAL"
    assert document["immutability"]["mutation_policy"] == "CONTENT_ADDRESSED_NEW_PACKAGE_REQUIRED"
    assert document["base_package"]["approval"]["state"] == "NOT_REQUESTED"
    assert "evidence_extensions" in document
    assert not any(key in document for key in ("applied", "registered"))

    schema = json.loads(
        (ROOT / "schemas" / "proposed-integration-package.schema.json").read_text()
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def test_package_mutation_before_submission_changes_digest_and_is_rejected(tmp_path) -> None:
    result, config = run_lifecycle(tmp_path)
    proposed = result.proposed_package
    assert proposed is not None
    mutable = dict(proposed.document)
    mutable["lifecycle_state"] = "TAMPERED"
    tampered = replace(proposed, document=mutable)
    store = ImmutablePackageStore(tmp_path / "another-store")
    with pytest.raises(ValueError):
        store.submit(tampered)


def test_submitted_package_tampering_invalidates_approval(tmp_path) -> None:
    result, config = run_lifecycle(tmp_path)
    store = ImmutablePackageStore(config.package_store_root)
    service = ApprovalBindingService(store, fixed_clock)
    decision = service.record_human_decision(
        result.approval_request,
        decision="APPROVED",
        actor_id="human:test-reviewer",
        authentication_ref="audit:test-signature",
        human_authority=True,
    )
    assert service.verify(decision, result.approval_request, result.submitted_package)

    path = Path(result.submitted_package.path)
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b" ")
    assert store.verify(result.submitted_package) is False
    assert service.verify(decision, result.approval_request, result.submitted_package) is False


def test_non_human_cannot_approve(tmp_path) -> None:
    result, config = run_lifecycle(tmp_path)
    service = ApprovalBindingService(
        ImmutablePackageStore(config.package_store_root), fixed_clock
    )
    with pytest.raises(PermissionError):
        service.record_human_decision(
            result.approval_request,
            decision="APPROVED",
            actor_id="engine:self",
            authentication_ref="none",
            human_authority=False,
        )


def test_modified_package_gets_distinct_approval_scope(tmp_path) -> None:
    first, config = run_lifecycle(tmp_path / "first")
    second, _ = run_lifecycle(tmp_path / "second")
    # Identical fixtures produce identical content and scope.
    assert first.approval_request.scope_digest == second.approval_request.scope_digest
    tampered = replace(
        second.submitted_package,
        package_digest="sha256:" + "f" * 64,
    )
    service = ApprovalBindingService(
        ImmutablePackageStore(config.package_store_root), fixed_clock
    )
    decision = service.record_human_decision(
        first.approval_request,
        decision="APPROVED",
        actor_id="human:test",
        authentication_ref="audit:test",
        human_authority=True,
    )
    assert service.verify(decision, first.approval_request, tampered) is False
