from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from model_integration_engine.application.acceptance import (
    AcceptanceConfig,
    GenericAcceptanceRunner,
)
from model_integration_engine.application.probes import BlockedProbeExecutionBackend
from model_integration_engine.capabilities.delta import GenericCapabilityDeltaComparator
from model_integration_engine.domain import (
    CapabilityClaim,
    CapabilityClass,
    EvidenceKind,
    EvidenceLevel,
    SubjectKind,
    SubjectRef,
    SupportState,
    ValidationState,
)
from model_integration_engine.evidence import sha256_digest
from model_integration_engine.inspectors.gguf import GGUFInspectionError, GGUFInspector
from model_integration_engine.sandbox.artifacts import _validate_media_type
from model_integration_engine.user_evidence import UserInputEvidenceCollector

from tests.phase2_support import FixtureTransport, fixed_clock
from tests.phase3_support import write_gguf

ENDPOINT = "http://fixture-ollama.invalid:11434"


def user_document():
    return {
        "schema_version": "0.1.0",
        "source_id": "independent-user-check",
        "observations": [
            {
                "subject_kind": "DEPLOYMENT",
                "observation_key": "user.runtime.tags.http_status",
                "value": 200,
                "level": "DETECTED_FROM_RUNTIME",
            }
        ],
    }


def test_user_input_evidence_is_distinct_and_cannot_claim_test_validation() -> None:
    deployment = SubjectRef(
        SubjectKind.DEPLOYMENT,
        "deployment:test",
        digest=sha256_digest("deployment"),
    )
    collector = UserInputEvidenceCollector(clock=fixed_clock)
    records = collector.collect(
        user_document(), subjects={SubjectKind.DEPLOYMENT: deployment}
    )
    assert len(records) == 1
    assert records[0].kind is EvidenceKind.USER_INPUT
    assert records[0].level is EvidenceLevel.DETECTED_FROM_RUNTIME
    assert records[0].observed_value["classification"] == "USER_SUPPLIED"

    invalid = user_document()
    invalid["observations"][0]["level"] = "VALIDATED_BY_TEST"
    with pytest.raises(ValueError, match="cannot claim"):
        collector.collect(invalid, subjects={SubjectKind.DEPLOYMENT: deployment})


def test_registry_delta_without_snapshot_is_explicitly_unknown() -> None:
    claim = CapabilityClaim(
        claim_id="claim:test",
        capability_key="generation.text",
        capability_class=CapabilityClass.MODEL_CAPABILITY,
        subject=SubjectRef(SubjectKind.DEPLOYMENT, "deployment:test"),
        support=SupportState.UNKNOWN,
        validation=ValidationState.UNVALIDATED,
        evidence_levels=(EvidenceLevel.UNKNOWN,),
        evidence_ids=(),
        assessed_at=fixed_clock(),
    )
    result = GenericCapabilityDeltaComparator().compare((claim,), None)
    assert result.status == "UNKNOWN_NO_REGISTRY_SNAPSHOT"
    assert result.baseline_snapshot_digest is None
    assert result.unknown == (claim.claim_id,)
    assert result.added == ()


def test_acceptance_uses_blocked_probe_contract_and_never_requests_approval(
    tmp_path,
) -> None:
    output = tmp_path / "acceptance"
    result = asyncio.run(
        GenericAcceptanceRunner(
            transport=FixtureTransport(), clock=fixed_clock
        ).run(
            AcceptanceConfig(
                endpoint=ENDPOINT,
                model_reference="example-model:4b",
                output_directory=output,
                user_evidence_document=user_document(),
            )
        )
    )
    assert result.state == "DRAFT_PENDING_APPROVAL"
    assert result.approval_requested is False
    assert result.lifecycle.approval_request is None
    package = json.loads(
        (output / "real-draft-integration-package.json").read_text()
    )
    assert package["lifecycle_state"] == "DRAFT_PENDING_APPROVAL"
    assert package["base_package"]["approval"]["state"] == "NOT_REQUESTED"

    user = json.loads((output / "user-supplied-evidence.json").read_text())
    live = json.loads((output / "live-runtime-evidence.json").read_text())
    assert user["evidence"]
    assert all(item["kind"] == "USER_INPUT" for item in user["evidence"])
    assert live["evidence"]
    assert all(item["kind"] != "USER_INPUT" for item in live["evidence"])

    probes = json.loads((output / "behavioral-probe-evidence.json").read_text())
    assert probes["status"] == "BLOCKED_PRODUCTION_SANDBOX_UNAVAILABLE"
    assert probes["production_security_boundary"] is False
    assert probes["results"]
    assert all(item["outcome"] == "BLOCKED" for item in probes["results"])
    assert {"ERROR_HANDLING", "TIMEOUT_HANDLING"} <= {
        item["kind"] for item in probes["results"]
    }
    assert isinstance(
        result.lifecycle.vertical_slice.probes.attestation.backend_id, str
    )
    assert result.lifecycle.vertical_slice.probes.attestation.isolated is False
    assert isinstance(BlockedProbeExecutionBackend(), BlockedProbeExecutionBackend)


def test_artifact_digest_is_bound_to_direct_gguf_bytes(tmp_path) -> None:
    path = write_gguf(tmp_path / "artifact.gguf")
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    result = GGUFInspector(clock=fixed_clock).inspect(
        path, expected_digest=digest
    )
    assert result.observed.file_digest == digest
    with pytest.raises(GGUFInspectionError) as error:
        GGUFInspector().inspect(path, expected_digest="sha256:" + "0" * 64)
    assert error.value.code == "GGUF_DIGEST_MISMATCH"


def test_acceptance_rejects_unbound_artifact_digest(tmp_path) -> None:
    with pytest.raises(ValueError, match="requires artifact_path"):
        AcceptanceConfig(
            endpoint=ENDPOINT,
            model_reference="example-model:4b",
            output_directory=tmp_path,
            artifact_digest="sha256:" + "a" * 64,
        )


def test_gguf_magic_validation_never_calls_whole_file_read(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "large.gguf"
    with path.open("wb") as handle:
        handle.write(b"GGUF")
        handle.seek(64 * 1024 * 1024)
        handle.write(b"\0")

    def forbidden_read_bytes(self):
        raise AssertionError("whole-file read attempted")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    _validate_media_type(path, "application/x-gguf")


def test_acceptance_production_source_has_no_named_model_logic() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "model_integration_engine"
    combined = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in root.rglob("*.py")
    )
    assert "qwen" not in combined
    assert "if model ==" not in combined
    assert "if model_name ==" not in combined
