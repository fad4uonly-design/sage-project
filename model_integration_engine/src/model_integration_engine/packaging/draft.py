"""Draft integration-package builder for the Phase 2 vertical slice."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from ..application.probes import ProbeBatchResult
from ..compatibility.evaluator import CompatibilityEvaluationResult
from ..contracts import TargetSystemProfile
from ..domain import AdapterCandidate, CapabilityClaim, EvidenceRecord, SubjectRef
from ..evidence import deterministic_id, sha256_digest
from ..phase2_models import (
    DiscoveredModelRecord,
    EnvironmentInfo,
    ModelInspectionResult,
    RuntimeRecord,
)
from ..plugins.ollama.adapter import OllamaAdapterConfig


@dataclass(frozen=True, slots=True)
class DraftPackageInput:
    run_id: str
    created_at: datetime
    engine_version: str
    runtime: RuntimeRecord
    model: DiscoveredModelRecord
    inspection: ModelInspectionResult
    adapter: AdapterCandidate
    adapter_config: OllamaAdapterConfig
    capabilities: tuple[CapabilityClaim, ...]
    evidence: tuple[EvidenceRecord, ...]
    probes: ProbeBatchResult
    compatibility: CompatibilityEvaluationResult
    target_profile: TargetSystemProfile
    environment: EnvironmentInfo
    live_validation: bool
    capability_delta: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DraftPackageArtifact:
    package_id: str
    package_digest: str
    document: dict[str, Any]


class DraftIntegrationPackageBuilder:
    schema_version = "0.1.0"

    def __init__(self, schema_path: Path | None = None) -> None:
        self.schema_path = schema_path or (
            Path(__file__).resolve().parents[3]
            / "schemas"
            / "integration-package.schema.json"
        )

    def build(self, value: DraftPackageInput) -> DraftPackageArtifact:
        package_id = deterministic_id(
            "integration-package-draft",
            value.run_id,
            value.model.deployment_subject.subject_id,
            value.adapter_config.configuration_digest,
            value.target_profile.profile_digest,
        )
        created_at = _time(value.created_at)
        evidence_ids = {item.evidence_id for item in value.evidence}
        validated_claims = [
            claim for claim in value.capabilities if claim.is_registry_eligible
        ]
        unknown_claims = [
            claim
            for claim in value.capabilities
            if not claim.is_registry_eligible
        ]

        model_details = value.inspection.details
        artifact_items = []
        if value.model.artifact_subject is not None:
            artifact_items.append(
                {
                    "artifact_id": value.model.artifact_subject.subject_id,
                    "format": _artifact_format(value.model.artifact_format),
                    "uri": (
                        "ollama-manifest://"
                        + value.runtime.subject.subject_id.replace(":", "-")
                        + "/"
                        + value.model.runtime_reference
                    ),
                    "media_type": "application/x-gguf"
                    if (value.model.artifact_format or "").lower() == "gguf"
                    else None,
                    "digest": value.model.artifact_subject.digest,
                    "size_bytes": value.model.size_bytes,
                    "file_count": 1,
                    "relationships": [],
                    "trust": "UNTRUSTED",
                    "read_only": True,
                    "evidence_ids": list(value.model.evidence_ids),
                }
            )

        inspections = []
        if value.inspection.report is not None:
            report = value.inspection.report
            inspections.append(
                {
                    "inspection_id": report.report_id,
                    "inspector_id": report.inspector_id,
                    "inspector_version": report.inspector_version,
                    "subject": _subject(report.subject),
                    "requested_levels": list(report.requested_levels),
                    "completed_levels": list(report.completed_levels),
                    "started_at": created_at,
                    "completed_at": created_at,
                    "completeness": report.completeness.value,
                    "findings": [
                        {
                            "path": finding.path,
                            "raw_value": finding.raw_value,
                            "normalized_value": finding.normalized_value,
                            "value_type": finding.value_type,
                            "source": {
                                "uri": finding.source.uri,
                                "digest": finding.source.digest,
                                "locator": finding.source.locator,
                            },
                            "evidence_level": finding.evidence_level.value,
                            "evidence_id": finding.evidence_id,
                            "warnings": list(finding.warnings),
                        }
                        for finding in report.findings
                    ],
                    "unknown_fields": dict(report.unknown_fields),
                    "contradictions": list(report.contradictions),
                    "evidence_ids": list(report.evidence_ids),
                }
            )

        attestation = value.probes.attestation
        sandbox_runs = []
        if attestation is not None:
            sandbox_runs.append(
                {
                    "run_id": attestation.run_id,
                    "backend_id": attestation.backend_id,
                    "backend_version": attestation.backend_version,
                    "job_digest": attestation.job_digest,
                    "outcome": "PASS" if value.probes.problem is None else "BLOCKED",
                    "requested_controls": list(attestation.requested_controls),
                    "enforced_controls": list(attestation.enforced_controls),
                    "missing_controls": list(attestation.missing_controls),
                    "allowed_endpoints": list(attestation.allowed_endpoints),
                    "resource_limits": dict(value.environment.attributes.get("resource_limits", {})),
                    "started_at": _time(attestation.started_at),
                    "completed_at": _time(attestation.completed_at),
                    "host_write_observed": attestation.host_write_observed,
                    "cleanup_complete": attestation.cleanup_complete,
                    "output_artifact_digests": sorted(
                        {
                            result.raw.output_digest
                            for result in value.probes.results
                            if result.raw.output_digest is not None
                        }
                    ),
                    "evidence_ids": [
                        item.evidence_id
                        for item in value.probes.evidence
                        if item.observation_key == "sandbox.isolation_attestation"
                    ],
                }
            )

        probe_outcomes = [result.raw.outcome.value for result in value.probes.results]
        if probe_outcomes and all(item == "PASS" for item in probe_outcomes):
            evaluation_verdict = "PASS"
        elif any(item == "PASS" for item in probe_outcomes):
            evaluation_verdict = "PARTIAL"
        elif probe_outcomes:
            evaluation_verdict = "FAIL"
        else:
            evaluation_verdict = "INCONCLUSIVE"
        case_by_id = {case.probe_id: case for case in value.probes.plan.cases}
        evaluations = [
            {
                "evaluation_id": deterministic_id(
                    "evaluation", value.probes.plan.plan_id, value.run_id
                ),
                "suite_id": value.probes.plan.suite_id,
                "suite_version": value.probes.plan.suite_version,
                "suite_digest": sha256_digest(
                    {
                        "suite": value.probes.plan.suite_id,
                        "version": value.probes.plan.suite_version,
                        "cases": [case.probe_id for case in value.probes.plan.cases],
                    }
                ),
                "subject": _subject(value.model.deployment_subject),
                "adapter_id": value.adapter.adapter_id,
                "sandbox_run_id": attestation.run_id if attestation else "not-run",
                "verdict": evaluation_verdict,
                "results": [
                    {
                        "test_id": result.raw.probe_id,
                        "suite_id": value.probes.plan.suite_id,
                        "suite_version": value.probes.plan.suite_version,
                        "subject": _subject(result.raw.subject),
                        "environment_id": value.environment.environment_id,
                        "fixture_digest": case_by_id[result.raw.probe_id].fixture_digest,
                        "outcome": result.raw.outcome.value,
                        "assertions": dict(result.raw.assertions),
                        "measurements": dict(result.raw.measurements),
                        "output_digest": result.raw.output_digest,
                        "evidence_ids": [result.evidence_id],
                    }
                    for result in value.probes.results
                ],
                "aggregate_metrics": {
                    "total": len(probe_outcomes),
                    "passed": probe_outcomes.count("PASS"),
                    "failed": probe_outcomes.count("FAIL"),
                    "errors": probe_outcomes.count("ERROR"),
                },
                "evidence_ids": [
                    result.evidence_id for result in value.probes.results
                ],
                "limitations": [
                    "Phase 2 minimal safe probes only; quality benchmarking is out of scope."
                ],
            }
        ]

        risk_items = []
        if value.model.identity_status != "CONTENT_ADDRESSED":
            risk_items.append(
                _risk(
                    "risk-model-identity",
                    "identity",
                    "Model identity is provisional because no valid runtime content digest was observed.",
                    "HIGH",
                    list(value.model.evidence_ids),
                    "Require a content digest before consequential integration.",
                    True,
                )
            )
        elif not model_details or not model_details.details.get("parent_model"):
            risk_items.append(
                _risk(
                    "risk-upstream-revision",
                    "identity",
                    "Runtime content is addressed, but the exact upstream revision is unverified.",
                    "MEDIUM",
                    list(value.model.evidence_ids),
                    "Keep behavioral evidence deployment-scoped.",
                    False,
                )
            )
        if not value.live_validation:
            risk_items.append(
                _risk(
                    "risk-fixture-only",
                    "validation",
                    "Results were produced with deterministic fixtures, not a live deployment.",
                    "HIGH",
                    [],
                    "Run the same plan against an approved live endpoint in a real sandbox.",
                    True,
                )
            )
        if value.probes.problem is not None:
            risk_items.append(
                _risk(
                    "risk-probe-boundary",
                    "sandbox",
                    value.probes.problem.message,
                    "CRITICAL",
                    list(value.probes.problem.evidence_ids),
                    "Resolve the sandbox blocker before live validation.",
                    True,
                )
            )

        configuration_values = {
            "runtime_id": value.runtime.subject.subject_id,
            "deployment_id": value.model.deployment_subject.subject_id,
            "model_reference": value.model.runtime_reference,
            "runtime_owns_template": value.adapter_config.runtime_owns_template,
            "lifecycle_state": "DRAFT_PENDING_APPROVAL",
            "environment": {
                "environment_id": value.environment.environment_id,
                "python_version": value.environment.python_version,
                "platform": value.environment.platform,
                "machine": value.environment.machine,
                "runtime_endpoint_locality": value.environment.runtime_endpoint_locality,
                "sandbox_backend_id": value.environment.sandbox_backend_id,
                "attributes": dict(value.environment.attributes),
            },
        }
        config_artifact_digest = sha256_digest(configuration_values)
        rollback_digest = sha256_digest(
            {
                "method": "remove-staged-binding",
                "target": value.target_profile.target.subject_id,
                "configuration": config_artifact_digest,
            }
        )
        proposed_change_digest = sha256_digest(
            {
                "operation": "ADD",
                "target": value.target_profile.target.subject_id,
                "configuration": config_artifact_digest,
            }
        )

        compatibility = value.compatibility.assessment
        document: dict[str, Any] = {
            "schema_version": self.schema_version,
            "package_id": package_id,
            "created_at": created_at,
            "package_state": "DRAFT",
            "engine": {
                "name": "model-integration-engine",
                "version": value.engine_version,
                "build_digest": sha256_digest(
                    {
                        "name": "model-integration-engine",
                        "version": value.engine_version,
                        "vertical_slice": "phase2-ollama-read-only",
                    }
                ),
                "contract_version": "0.1.0",
                "policy_versions": {
                    "evidence": "0.2.0",
                    "capability": "0.2.0",
                    "compatibility": compatibility.policy_version,
                    "sandbox": "0.2.0",
                },
            },
            "workflow": {
                "run_id": value.run_id,
                "stage": "PROPOSED",
                "idempotency_key": deterministic_id(
                    "idempotency",
                    value.model.deployment_subject.digest,
                    value.adapter_config.configuration_digest,
                    value.target_profile.profile_digest,
                ),
                "started_at": created_at,
                "updated_at": created_at,
                "transitions": [
                    {
                        "transition_id": deterministic_id(
                            "transition", value.run_id, "PROPOSED"
                        ),
                        "from": "EVALUATED",
                        "to": "PROPOSED",
                        "at": created_at,
                        "actor_type": "ENGINE",
                        "actor_id": "mie.phase2.vertical-slice",
                        "input_digest": sha256_digest(
                            sorted(evidence_ids)
                        ),
                        "output_digest": proposed_change_digest,
                        "evidence_ids": sorted(evidence_ids),
                    }
                ],
            },
            "model": {
                "model_id": value.model.model_subject.subject_id,
                "names": list(value.model.aliases) or [value.model.runtime_reference],
                "publisher": None,
                "upstream_uri": None,
                "revision": None,
                "architecture_label": model_details.architecture if model_details else None,
                "artifact_ids": [
                    value.model.artifact_subject.subject_id
                ]
                if value.model.artifact_subject
                else [],
                "identity_basis_evidence_ids": list(value.model.evidence_ids),
                "identity_status": "RECONCILED"
                if value.model.identity_status == "CONTENT_ADDRESSED"
                else "PROVISIONAL",
            },
            "artifacts": artifact_items,
            "runtime": {
                "runtime_id": value.runtime.subject.subject_id,
                "kind": value.runtime.kind,
                "version": value.runtime.version,
                "endpoint": value.runtime.endpoint,
                "locality": value.runtime.locality.value,
                "protocols": list(value.runtime.protocol_names),
                "deployment_id": value.model.deployment_subject.subject_id,
                "model_reference": value.model.runtime_reference,
                "model_digest": value.model.content_digest,
                "authentication_ref": None,
                "evidence_ids": list(value.runtime.evidence_ids),
            },
            "inspections": inspections,
            "capabilities": [_capability(item) for item in value.capabilities],
            "evidence": [_evidence(item) for item in value.evidence],
            "compatibility": {
                "assessment_id": compatibility.assessment_id,
                "status": compatibility.status.value,
                "target_profile": {
                    "target_id": value.target_profile.target.subject_id,
                    "version": value.target_profile.profile_version,
                    "digest": value.target_profile.profile_digest,
                },
                "subject": _subject(compatibility.subject),
                "requirements": [
                    {
                        "requirement_id": item.requirement_id,
                        "description": item.description,
                        "mandatory": item.mandatory,
                        "status": item.status.value,
                        "evidence_ids": list(item.evidence_ids),
                        "adapter_obligations": list(item.adapter_obligations),
                        "remediation": list(item.remediation),
                        "risks": list(item.risks),
                    }
                    for item in compatibility.requirements
                ],
                "blockers": list(compatibility.blockers),
                "unknowns": list(compatibility.unknowns),
                "required_permissions": list(compatibility.required_permissions),
                "policy_version": compatibility.policy_version,
                "assessed_at": created_at,
            },
            "capability_delta": value.capability_delta
            or {
                "baseline_snapshot_digest": value.target_profile.capability_snapshot_digest,
                "added": [claim.claim_id for claim in validated_claims],
                "improved": [],
                "redundant": [],
                "regressed": [],
                "unknown": [claim.claim_id for claim in unknown_claims],
                "policy_version": "delta-policy-0.2.0",
            },
            "adapter": {
                "disposition": "CONFIGURE",
                "adapter_id": value.adapter.adapter_id,
                "version": value.adapter.adapter_version,
                "origin": value.adapter.origin.value,
                "trust": value.adapter.trust_state.value,
                "contract_version": value.adapter.contract_version,
                "source_manifest_digest": value.adapter.source_manifest_digest,
                "configuration_digest": value.adapter_config.configuration_digest,
                "supported_operations": list(value.adapter.supported_operations),
                "required_permissions": list(value.adapter.required_permissions),
                "validation": value.adapter.validation.value,
                "evidence_ids": list(value.adapter.evidence_ids),
                "limitations": list(value.adapter.limitations),
                "generation_reason": None,
            },
            "configuration": {
                "manifest_digest": value.adapter_config.configuration_digest,
                "artifacts": [
                    {
                        "path": "config/model-binding.json",
                        "digest": config_artifact_digest,
                    }
                ],
                "values": configuration_values,
                "contains_secrets": False,
            },
            "sandbox": {
                "required": True,
                "policy_version": "sandbox-policy-0.2.0",
                "runs": sandbox_runs,
            },
            "evaluations": evaluations,
            "regression": {
                "preflight_outcome": "NOT_RUN",
                "baseline_run_id": None,
                "candidate_run_id": None,
                "baseline_digest": None,
                "candidate_digest": None,
                "suite_ref": None,
                "affected_tests": [case.probe_id for case in value.probes.plan.cases],
                "known_baseline_failures": [],
                "evidence_ids": [],
                "post_application_outcome": "NOT_APPLICABLE",
            },
            "risks": risk_items,
            "permissions": [
                {
                    "permission_id": "permission-ollama-read-infer",
                    "scope": f"network:{value.runtime.endpoint}",
                    "purpose": "Read runtime metadata and run bounded non-destructive probes.",
                    "stage": "DISCOVER_TO_EVALUATE",
                    "required": True,
                    "duration": "single vertical-slice run",
                    "data_exposure": "non-sensitive deterministic probe prompts",
                    "mitigations": [
                        "Endpoint allowlist",
                        "No model mutation methods",
                        "Sandbox resource limits",
                    ],
                },
                {
                    "permission_id": "permission-engine-workspace",
                    "scope": "filesystem:engine-workspace-only",
                    "purpose": "Write evidence and the draft package.",
                    "stage": "ALL",
                    "required": True,
                    "duration": "single vertical-slice run",
                    "data_exposure": "sanitized metadata and evidence",
                    "mitigations": ["No target/SAGE mount", "No credentials in package"],
                },
            ],
            "proposed_changes": [
                {
                    "change_id": "change-staged-model-binding",
                    "target": value.target_profile.target.subject_id,
                    "operation": "ADD",
                    "before_digest": None,
                    "after_digest": config_artifact_digest,
                    "artifact_ref": "config/model-binding.json",
                    "reason": "Propose a generic adapter binding; no change is applied in Phase 2.",
                    "capability_claim_ids": [
                        claim.claim_id for claim in validated_claims
                    ],
                    "preconditions": [
                        "Live validation replaces fixture evidence where applicable.",
                        "Explicit user approval is recorded for the exact package digest.",
                        "Preflight regression succeeds.",
                    ],
                    "reversible": True,
                    "rollback_ref": "rollback-remove-staged-binding",
                    "affected_test_ids": [
                        case.probe_id for case in value.probes.plan.cases
                    ],
                }
            ],
            "rollback": {
                "plan_id": "rollback-remove-staged-binding",
                "plan_digest": rollback_digest,
                "method": "Remove the proposed model binding and restore the prior target snapshot.",
                "preconditions": ["Prior target snapshot is available."],
                "steps": [
                    "Disable the proposed binding.",
                    "Restore the prior target snapshot.",
                    "Rerun target smoke tests.",
                ],
                "restores_digest": value.target_profile.capability_snapshot_digest,
                "tested": False,
                "test_evidence_ids": [],
                "irreversible_effects": [],
            },
            "approval": {
                "state": "NOT_REQUESTED",
                "scope": None,
                "actor_id": None,
                "decided_at": None,
                "event_ref": None,
                "conditions": [
                    "Machine lifecycle state is DRAFT_PENDING_APPROVAL; Phase 2 stops here."
                ],
            },
            "provenance": {
                "inputs": [
                    {
                        "item_id": value.model.deployment_subject.subject_id,
                        "kind": "ollama-deployment",
                        "uri": f"{value.runtime.endpoint}/api/show",
                        "digest": value.model.deployment_subject.digest,
                        "license": None,
                        "evidence_ids": list(value.model.evidence_ids),
                    }
                ],
                "generated_outputs": [
                    {
                        "item_id": "config-model-binding",
                        "kind": "adapter-configuration",
                        "uri": f"package://{package_id}/config/model-binding.json",
                        "digest": config_artifact_digest,
                        "license": None,
                        "evidence_ids": list(value.adapter.evidence_ids),
                    }
                ],
                "canonicalization_policy": "mie-canonical-json-phase2-0.2.0",
                "contains_credentials": False,
            },
            "assumptions": [
                {
                    "assumption_id": "assumption-upstream-revision",
                    "statement": "The runtime content digest corresponds to the intended upstream model revision.",
                    "verification_status": "UNVERIFIED",
                    "evidence_ids": list(value.model.evidence_ids),
                    "impact": "Logical model identity remains provisional; behavioral evidence is deployment-scoped.",
                }
            ],
            "limitations": [
                "Phase 2 stops before approval, application, regression, or registry update.",
                "No SAGE files or interfaces were accessed.",
                "Fixture evidence is not a substitute for live deployment validation."
                if not value.live_validation
                else "Live results apply only to the recorded deployment and environment.",
            ],
        }

        self.validate(document)
        package_digest = sha256_digest(document)
        return DraftPackageArtifact(
            package_id=package_id,
            package_digest=package_digest,
            document=document,
        )

    def validate(self, document: dict[str, Any]) -> None:
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
        if errors:
            details = "; ".join(
                f"{'/'.join(map(str, error.path)) or '/'}: {error.message}"
                for error in errors[:10]
            )
            raise ValueError(f"Draft integration package is invalid: {details}")


def _time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("package timestamps must be timezone-aware")
    return value.isoformat().replace("+00:00", "Z")


def _subject(value: SubjectRef) -> dict[str, Any]:
    return {
        "kind": value.kind.value,
        "subject_id": value.subject_id,
        "version": value.version,
        "digest": value.digest,
    }


def _capability(value: CapabilityClaim) -> dict[str, Any]:
    return {
        "claim_id": value.claim_id,
        "capability_key": value.capability_key,
        "capability_class": value.capability_class.value,
        "subject": _subject(value.subject),
        "support": value.support.value,
        "validation": value.validation.value,
        "evidence_levels": [item.value for item in value.evidence_levels],
        "evidence_ids": list(value.evidence_ids),
        "parameters": dict(value.parameters),
        "limitations": list(value.limitations),
        "contradictions": list(value.contradictions),
        "policy_version": value.policy_version,
        "assessed_at": _time(value.assessed_at) if value.assessed_at else "1970-01-01T00:00:00Z",
    }


def _evidence(value: EvidenceRecord) -> dict[str, Any]:
    return {
        "evidence_id": value.evidence_id,
        "kind": value.kind.value,
        "level": value.level.value,
        "subject": _subject(value.subject),
        "observation_key": value.observation_key,
        "observed_value": value.observed_value,
        "source": {
            "uri": value.source.uri,
            "digest": value.source.digest,
            "locator": value.source.locator,
        },
        "collector_id": value.collector_id,
        "collector_version": value.collector_version,
        "collected_at": _time(value.collected_at),
        "outcome": value.outcome.value if value.outcome else None,
        "environment_id": value.environment_id,
        "derived_from": list(value.derived_from),
        "supersedes": list(value.supersedes),
        "redacted": value.redacted,
    }


def _artifact_format(value: str | None) -> str:
    normalized = (value or "UNKNOWN").upper()
    return normalized if normalized in {"GGUF", "MODEL_DIRECTORY", "SAFETENSORS", "ONNX", "OTHER"} else "UNKNOWN"


def _risk(
    risk_id: str,
    category: str,
    description: str,
    severity: str,
    evidence_ids: list[str],
    mitigation: str,
    blocking: bool,
) -> dict[str, Any]:
    return {
        "risk_id": risk_id,
        "category": category,
        "description": description,
        "severity": severity,
        "likelihood": "MEDIUM",
        "evidence_ids": evidence_ids,
        "mitigation": mitigation,
        "residual_severity": "HIGH" if blocking else "LOW",
        "blocking": blocking,
    }
