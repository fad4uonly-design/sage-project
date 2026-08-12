"""Structured security assessment for proposed integration packages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..domain import JSONValue, TrustState
from ..evidence import sha256_digest
from ..sandbox.contracts import IsolationClass, SandboxOutcome


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    finding_id: str
    category: str
    severity: str
    blocking: bool
    description: str
    mitigation: str


@dataclass(frozen=True, slots=True)
class SecurityAssessment:
    assessment_id: str
    verdict: str
    sandbox_isolation_class: str
    generated_code_trust: str
    permissions_digest: str
    artifact_manifest_digest: str | None
    findings: tuple[SecurityFinding, ...]
    policy_version: str

    def as_dict(self) -> Mapping[str, JSONValue]:
        return {
            "assessment_id": self.assessment_id,
            "verdict": self.verdict,
            "sandbox_isolation_class": self.sandbox_isolation_class,
            "generated_code_trust": self.generated_code_trust,
            "permissions_digest": self.permissions_digest,
            "artifact_manifest_digest": self.artifact_manifest_digest,
            "findings": [
                {
                    "finding_id": item.finding_id,
                    "category": item.category,
                    "severity": item.severity,
                    "blocking": item.blocking,
                    "description": item.description,
                    "mitigation": item.mitigation,
                }
                for item in self.findings
            ],
            "policy_version": self.policy_version,
        }


class SecurityAssessor:
    policy_version = "security-policy-0.3.0"

    def assess(
        self,
        *,
        isolation_class: IsolationClass,
        sandbox_outcome: SandboxOutcome | None,
        security_boundary_claimed: bool,
        cleanup_complete: bool,
        adapter_trust: TrustState,
        permissions: tuple[str, ...],
        artifact_manifest_digest: str | None,
        identity_collision: bool,
        live_validation: bool,
    ) -> SecurityAssessment:
        findings: list[SecurityFinding] = []

        def add(fid, category, severity, blocking, description, mitigation):
            findings.append(
                SecurityFinding(fid, category, severity, blocking, description, mitigation)
            )

        if isolation_class is not IsolationClass.PRODUCTION_SECURITY_BOUNDARY:
            add(
                "sandbox-not-production",
                "sandbox",
                "HIGH",
                live_validation or adapter_trust is TrustState.UNTRUSTED_GENERATED,
                "The selected backend is not a production security boundary.",
                "Use a backend that truthfully enforces filesystem, network, and permission isolation.",
            )
        if sandbox_outcome not in {None, SandboxOutcome.PASS}:
            add(
                "sandbox-run-failed",
                "sandbox",
                "CRITICAL",
                True,
                f"Sandbox outcome was {sandbox_outcome.value}.",
                "Resolve the sandbox failure and rerun the exact package inputs.",
            )
        if security_boundary_claimed and isolation_class is not IsolationClass.PRODUCTION_SECURITY_BOUNDARY:
            add(
                "false-isolation-claim",
                "sandbox",
                "CRITICAL",
                True,
                "A non-production backend claimed a security boundary.",
                "Reject the backend and investigate attestation integrity.",
            )
        if not cleanup_complete:
            add(
                "sandbox-cleanup-failed",
                "cleanup",
                "HIGH",
                True,
                "Sandbox cleanup did not complete.",
                "Quarantine residual state and use a disposable backend.",
            )
        if adapter_trust is TrustState.UNTRUSTED_GENERATED:
            add(
                "generated-adapter-untrusted",
                "generated_code",
                "HIGH",
                True,
                "Generated adapter proposal remains untrusted.",
                "Run static review and production-isolated validation before acceptance.",
            )
        if identity_collision:
            add(
                "model-alias-collision",
                "identity",
                "HIGH",
                True,
                "A runtime alias resolved to multiple content digests.",
                "Require explicit content digest selection and new approval scope.",
            )
        if artifact_manifest_digest is None:
            add(
                "artifact-manifest-missing",
                "artifact",
                "HIGH",
                True,
                "No resolver-verified artifact manifest is available.",
                "Resolve and verify sandbox artifacts before evidence ingestion.",
            )
        broad_permissions = [
            item for item in permissions if item.endswith(":*") or item in {"network:*", "filesystem:*"}
        ]
        if broad_permissions:
            add(
                "broad-permissions",
                "permissions",
                "HIGH",
                True,
                "Permission scope contains wildcard access.",
                "Replace wildcards with exact endpoint/path scopes.",
            )
        blocking = any(item.blocking for item in findings)
        verdict = "BLOCKED" if blocking else ("CONDITIONAL" if findings else "PASS")
        permissions_digest = sha256_digest(sorted(permissions))
        assessment_id = "security:" + sha256_digest(
            {
                "policy": self.policy_version,
                "isolation": isolation_class.value,
                "permissions": permissions_digest,
                "artifacts": artifact_manifest_digest,
                "findings": [item.finding_id for item in findings],
            }
        ).removeprefix("sha256:")[:32]
        return SecurityAssessment(
            assessment_id=assessment_id,
            verdict=verdict,
            sandbox_isolation_class=isolation_class.value,
            generated_code_trust=adapter_trust.value,
            permissions_digest=permissions_digest,
            artifact_manifest_digest=artifact_manifest_digest,
            findings=tuple(findings),
            policy_version=self.policy_version,
        )
