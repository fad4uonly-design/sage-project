"""Atomic validated-capability registry with strict eligibility gates."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from ..approval.binding import (
    ApprovalBindingService,
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
)
from ..evidence import sha256_digest
from ..packaging.proposed import SubmittedPackage
from ..regression.framework import RegressionComparison


class RegistryEligibilityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RegistryUpdate:
    registry_digest: str
    registry_version: str
    entry_id: str
    path: str


class ValidatedCapabilityRegistry:
    def __init__(self, path: Path, approval_service: ApprovalBindingService) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.approval_service = approval_service
        project_root = Path(__file__).resolve().parents[3]
        self.schema = json.loads(
            (project_root / "schemas" / "capability-registry.schema.json").read_text(encoding="utf-8")
        )

    def register(
        self,
        *,
        entry: Mapping[str, Any],
        submitted: SubmittedPackage,
        approval_request: ApprovalRequestRecord,
        approval_decision: ApprovalDecisionRecord,
        post_regression: RegressionComparison,
    ) -> RegistryUpdate:
        if not self.approval_service.verify(
            approval_decision, approval_request, submitted
        ):
            raise RegistryEligibilityError("REGISTRY_APPROVAL_INVALID", "Approval binding is invalid")
        package_document = self.approval_service.store.read(submitted)
        if package_document["security_assessment"]["verdict"] == "BLOCKED":
            raise RegistryEligibilityError(
                "REGISTRY_SECURITY_BLOCKED", "Blocking security assessment prevents registration"
            )
        if not post_regression.passed:
            raise RegistryEligibilityError(
                "REGISTRY_REGRESSION_FAILED", "Post-application regression must pass"
            )
        item = json.loads(json.dumps(entry))
        if item.get("status") != "ACTIVE":
            raise RegistryEligibilityError(
                "REGISTRY_ENTRY_NOT_ACTIVE", "New registration must be ACTIVE"
            )
        package_ref = item.get("integration_package", {})
        if package_ref.get("package_digest") != submitted.package_digest:
            raise RegistryEligibilityError(
                "REGISTRY_PACKAGE_MISMATCH", "Registry package digest mismatch"
            )
        if package_ref.get("post_application_regression_outcome") != "PASS":
            raise RegistryEligibilityError(
                "REGISTRY_REGRESSION_UNPROVEN", "Registry entry lacks passing regression"
            )
        capabilities = item.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            raise RegistryEligibilityError(
                "REGISTRY_CAPABILITIES_MISSING", "At least one capability is required"
            )
        for capability in capabilities:
            if (
                capability.get("validation") != "VALIDATED"
                or "VALIDATED_BY_TEST" not in capability.get("evidence_levels", [])
                or capability.get("support") not in {"SUPPORTED", "PARTIAL"}
                or not capability.get("evidence")
                or any(ev.get("outcome") != "PASS" for ev in capability.get("evidence", []))
            ):
                raise RegistryEligibilityError(
                    "REGISTRY_CAPABILITY_UNVALIDATED",
                    f"Capability {capability.get('capability_key')} is not eligible",
                )

        current = self.snapshot()
        if any(existing.get("registration_id") == item.get("registration_id") for existing in current["entries"]):
            raise RegistryEligibilityError("REGISTRY_ENTRY_DUPLICATE", "Registration ID already exists")
        document = {
            "schema_version": "0.1.0",
            "registry_version": str(int(current["registry_version"]) + 1),
            "registry_id": current["registry_id"],
            "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "policy_version": current["policy_version"],
            "previous_registry_digest": sha256_digest(current),
            "entries": [*current["entries"], item],
        }
        errors = list(
            Draft202012Validator(
                self.schema, format_checker=FormatChecker()
            ).iter_errors(document)
        )
        if errors:
            raise RegistryEligibilityError(
                "REGISTRY_SCHEMA_INVALID", errors[0].message
            )
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, self.path)
        return RegistryUpdate(
            registry_digest=sha256_digest(document),
            registry_version=document["registry_version"],
            entry_id=item["registration_id"],
            path=str(self.path),
        )

    def snapshot(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": "0.1.0",
                "registry_version": "0",
                "registry_id": "mie-validated-capability-registry",
                "updated_at": "1970-01-01T00:00:00Z",
                "policy_version": "registry-policy-0.3.0",
                "previous_registry_digest": None,
                "entries": [],
            }
        value = json.loads(self.path.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(self.schema).iter_errors(value))
        if errors:
            raise RegistryEligibilityError("REGISTRY_CORRUPT", errors[0].message)
        return value


class CapabilityHypothesisStore:
    """Separate untrusted store; contents are never registry capabilities."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, proposal_id: str, claims: list[Mapping[str, Any]]) -> str:
        current = []
        if self.path.exists():
            current = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(current, list):
                raise ValueError("hypothesis store is malformed")
        record = {
            "proposal_id": proposal_id,
            "trust": "UNVALIDATED_HYPOTHESES",
            "claims": json.loads(json.dumps(claims)),
        }
        current.append(record)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
        return sha256_digest(record)
