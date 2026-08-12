"""Phase 3 proposed-package envelope and immutable content-addressed store."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from ..evidence import canonical_json_bytes, deterministic_id, sha256_digest
from ..identity.reconciliation import ReconciledIdentity
from ..sandbox.artifacts import ArtifactResolution
from ..security.assessment import SecurityAssessment


@dataclass(frozen=True, slots=True)
class ProposedPackageInput:
    created_at: datetime
    base_package: Mapping[str, Any]
    identity: ReconciledIdentity
    environment_id: str
    environment_digest: str
    environment_attributes: Mapping[str, Any]
    adapter_id: str
    adapter_artifact_digest: str
    adapter_configuration_digest: str
    adapter_trust: str
    adapter_resolution: str
    artifact_resolution: ArtifactResolution | None
    security: SecurityAssessment
    regression_plan: Mapping[str, Any]
    target_snapshot: Mapping[str, Any]
    change_set: Mapping[str, Any]
    rollback_plan: Mapping[str, Any]
    permissions: tuple[str, ...]
    policy_versions: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ProposedPackage:
    package_id: str
    document: Mapping[str, Any]
    pre_submission_digest: str


@dataclass(frozen=True, slots=True)
class SubmittedPackage:
    package_id: str
    package_digest: str
    path: str
    size_bytes: int


class ProposedIntegrationPackageBuilder:
    def build(self, value: ProposedPackageInput) -> ProposedPackage:
        base = json.loads(json.dumps(value.base_package))
        base_digest = sha256_digest(base)
        change_set = _digest_object(value.change_set, "change-set")
        target = _digest_object(value.target_snapshot, "target-snapshot")
        rollback = _digest_object(value.rollback_plan, "rollback-plan")
        regression = _digest_object(value.regression_plan, "regression-plan")
        permissions = tuple(sorted(set(value.permissions)))
        permission_digest = sha256_digest(list(permissions))
        policies = dict(sorted(value.policy_versions.items()))
        policy_digest = sha256_digest(policies)
        artifacts = []
        manifest_digest = None
        if value.artifact_resolution is not None:
            manifest_digest = value.artifact_resolution.manifest_digest
            artifacts = [
                {
                    "artifact_id": item.artifact_id,
                    "digest": item.digest,
                    "media_type": item.media_type,
                    "size_bytes": item.size_bytes,
                    "provenance": {
                        "run_id": item.provenance.run_id,
                        "source_relative_path": item.provenance.source_relative_path,
                        "source_reported_digest": item.provenance.source_reported_digest,
                        "resolver_id": item.provenance.resolver_id,
                        "resolver_version": item.provenance.resolver_version,
                    },
                }
                for item in value.artifact_resolution.artifacts
            ]
        package_material = {
            "base_package_digest": base_digest,
            "composition": value.identity.composition.digest,
            "environment": value.environment_digest,
            "adapter": value.adapter_artifact_digest,
            "configuration": value.adapter_configuration_digest,
            "target": target["digest"],
            "changes": change_set["digest"],
            "rollback": rollback["digest"],
            "policies": policy_digest,
        }
        package_id = deterministic_id("proposed-integration-package", package_material)
        document = {
            "schema_version": "0.3.0",
            "package_id": package_id,
            "created_at": _time(value.created_at),
            "lifecycle_state": "DRAFT_PENDING_APPROVAL",
            "base_package": base,
            "base_package_digest": base_digest,
            "reconciled_identity": {
                "logical_model_id": value.identity.logical_model.subject_id,
                "artifact_digest": value.identity.artifact.digest if value.identity.artifact else None,
                "deployment_id": value.identity.deployment.subject_id,
                "composition_id": value.identity.composition.subject_id,
                "composition_digest": value.identity.composition.digest,
                "status": value.identity.identity_status,
                "alias_collision": value.identity.alias_collision,
                "evidence_ids": [item.evidence_id for item in value.identity.evidence],
            },
            "evidence_extensions": [
                {
                    "evidence_id": item.evidence_id,
                    "kind": item.kind.value,
                    "level": item.level.value,
                    "subject": {
                        "kind": item.subject.kind.value,
                        "subject_id": item.subject.subject_id,
                        "version": item.subject.version,
                        "digest": item.subject.digest,
                    },
                    "observation_key": item.observation_key,
                    "observed_value": item.observed_value,
                    "source": {
                        "uri": item.source.uri,
                        "digest": item.source.digest,
                        "locator": item.source.locator,
                    },
                    "collector_id": item.collector_id,
                    "collector_version": item.collector_version,
                    "collected_at": _time(item.collected_at),
                    "outcome": item.outcome.value if item.outcome else None,
                    "environment_id": item.environment_id,
                    "derived_from": list(item.derived_from),
                }
                for item in value.identity.evidence
            ],
            "environment_identity": {
                "id": value.environment_id,
                "digest": value.environment_digest,
                "attributes": dict(value.environment_attributes),
            },
            "adapter_artifact": {
                "adapter_id": value.adapter_id,
                "artifact_digest": value.adapter_artifact_digest,
                "configuration_digest": value.adapter_configuration_digest,
                "trust": value.adapter_trust,
                "resolution": value.adapter_resolution,
                "sandbox_required": value.adapter_trust == "UNTRUSTED_GENERATED",
            },
            "artifact_manifest": {
                "manifest_digest": manifest_digest,
                "artifacts": artifacts,
            },
            "security_assessment": value.security.as_dict(),
            "regression_plan": regression,
            "target_snapshot": target,
            "change_set": change_set,
            "rollback_plan": rollback,
            "permission_set": {
                "digest": permission_digest,
                "permissions": list(permissions),
            },
            "policy_set": {"digest": policy_digest, "versions": policies},
            "approval_binding_material": {
                "change_set_digest": change_set["digest"],
                "target_snapshot_digest": target["digest"],
                "permission_set_digest": permission_digest,
                "policy_digest": policy_digest,
                "rollback_plan_digest": rollback["digest"],
            },
            "immutability": {
                "canonicalization": "mie-canonical-json-phase3-0.3.0",
                "mutation_policy": "CONTENT_ADDRESSED_NEW_PACKAGE_REQUIRED",
            },
        }
        digest = sha256_digest(document)
        return ProposedPackage(package_id=package_id, document=document, pre_submission_digest=digest)


class ImmutablePackageStore:
    """Validate and store immutable packages by content digest."""

    def __init__(self, root: Path, project_root: Path | None = None) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.base_schema = json.loads(
            (self.project_root / "schemas" / "integration-package.schema.json").read_text(encoding="utf-8")
        )
        self.proposed_schema = json.loads(
            (self.project_root / "schemas" / "proposed-integration-package.schema.json").read_text(encoding="utf-8")
        )

    def submit(self, package: ProposedPackage) -> SubmittedPackage:
        document = json.loads(json.dumps(package.document))
        self._validate(document)
        payload = canonical_json_bytes(document)
        digest = sha256_digest(payload)
        if digest != package.pre_submission_digest:
            raise ValueError("package changed between build and submission")
        digest_hex = digest.removeprefix("sha256:")
        destination = self.root / digest_hex[:2] / f"{digest_hex}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != payload:
                raise ValueError("content-addressed package collision")
        else:
            temporary = destination.with_suffix(".tmp")
            temporary.write_bytes(payload)
            os.chmod(temporary, 0o400)
            os.replace(temporary, destination)
        return SubmittedPackage(
            package_id=package.package_id,
            package_digest=digest,
            path=str(destination),
            size_bytes=len(payload),
        )

    def verify(self, submitted: SubmittedPackage) -> bool:
        path = Path(submitted.path)
        if not path.is_file():
            return False
        data = path.read_bytes()
        if len(data) != submitted.size_bytes or sha256_digest(data) != submitted.package_digest:
            return False
        try:
            self._validate(json.loads(data))
        except (ValueError, json.JSONDecodeError):
            return False
        return True

    def read(self, submitted: SubmittedPackage) -> Mapping[str, Any]:
        if not self.verify(submitted):
            raise ValueError("submitted package failed integrity validation")
        return json.loads(Path(submitted.path).read_bytes())

    def _validate(self, document: Mapping[str, Any]) -> None:
        proposed_validator = Draft202012Validator(
            self.proposed_schema, format_checker=FormatChecker()
        )
        errors = list(proposed_validator.iter_errors(document))
        if errors:
            raise ValueError("proposed package invalid: " + errors[0].message)
        base = document["base_package"]
        base_errors = list(
            Draft202012Validator(
                self.base_schema, format_checker=FormatChecker()
            ).iter_errors(base)
        )
        if base_errors:
            raise ValueError("base package invalid: " + base_errors[0].message)
        if sha256_digest(base) != document["base_package_digest"]:
            raise ValueError("base package digest mismatch")
        binding = document["approval_binding_material"]
        checks = {
            "change_set_digest": document["change_set"]["digest"],
            "target_snapshot_digest": document["target_snapshot"]["digest"],
            "permission_set_digest": document["permission_set"]["digest"],
            "policy_digest": document["policy_set"]["digest"],
            "rollback_plan_digest": document["rollback_plan"]["digest"],
        }
        if dict(binding) != checks:
            raise ValueError("approval binding material mismatch")


def _digest_object(value: Mapping[str, Any], default_prefix: str) -> dict[str, Any]:
    result = json.loads(json.dumps(value))
    result.setdefault("id", deterministic_id(default_prefix, result))
    digest_material = {key: item for key, item in result.items() if key != "digest"}
    result["digest"] = sha256_digest(digest_material)
    return result


def _time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("proposed package timestamp must be timezone-aware")
    return value.isoformat().replace("+00:00", "Z")
