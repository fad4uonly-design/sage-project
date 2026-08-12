"""Part 3 end-to-end workflow through immutable approval request, then STOP."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..adapters.engine import (
    AdapterCatalog,
    AdapterRequirement,
    GenericAdapterEngine,
    generic_ollama_adapter_spec,
)
from ..approval.binding import ApprovalBindingService, ApprovalRequestRecord
from ..contracts import OperationContext
from ..domain import SubjectKind, SubjectRef, TrustState
from ..evidence import sha256_digest, utc_now
from ..identity.reconciliation import (
    IdentityInputs,
    IdentityLedger,
    ModelIdentityReconciler,
    ReconciledIdentity,
)
from ..packaging.proposed import (
    ImmutablePackageStore,
    ProposedIntegrationPackageBuilder,
    ProposedPackage,
    ProposedPackageInput,
    SubmittedPackage,
)
from ..sandbox.artifacts import ArtifactResolution
from ..sandbox.contracts import IsolationClass, SandboxOutcome
from ..security.assessment import SecurityAssessment, SecurityAssessor
from .vertical_slice import (
    Phase2VerticalSliceEngine,
    VerticalSliceConfig,
    VerticalSliceResult,
)


@dataclass(frozen=True, slots=True)
class Part3LifecycleConfig:
    vertical_slice: VerticalSliceConfig
    package_store_root: Path
    identity_ledger_path: Path
    artifact_resolution: ArtifactResolution | None = None
    request_approval: bool = True


@dataclass(frozen=True, slots=True)
class Part3LifecycleResult:
    state: str
    vertical_slice: VerticalSliceResult
    identity: ReconciledIdentity | None
    security: SecurityAssessment | None
    proposed_package: ProposedPackage | None
    submitted_package: SubmittedPackage | None
    approval_request: ApprovalRequestRecord | None
    problem: str | None


@dataclass(slots=True)
class Part3LifecycleEngine:
    phase2: Phase2VerticalSliceEngine
    clock: callable = utc_now

    async def run(
        self,
        config: Part3LifecycleConfig,
        context: OperationContext,
    ) -> Part3LifecycleResult:
        vertical = await self.phase2.run(config.vertical_slice, context)
        if vertical.package is None or vertical.discovery.runtime is None:
            return Part3LifecycleResult(
                state="FAILED",
                vertical_slice=vertical,
                identity=None,
                security=None,
                proposed_package=None,
                submitted_package=None,
                approval_request=None,
                problem=vertical.problem.message if vertical.problem else "vertical slice failed",
            )
        base = vertical.package.document
        inspection = vertical.inspection
        if inspection is None or inspection.details is None:
            return Part3LifecycleResult(
                "FAILED", vertical, None, None, None, None, None, "inspection missing"
            )
        deployment_id = base["runtime"]["deployment_id"]
        discovered = next(
            item
            for item in vertical.discovery.models
            if item.deployment_subject.subject_id == deployment_id
        )
        runtime = vertical.discovery.runtime

        catalog = AdapterCatalog()
        catalog.register(generic_ollama_adapter_spec())
        adapter_engine = GenericAdapterEngine(catalog)
        adapter_resolution = adapter_engine.resolve(
            AdapterRequirement(
                runtime_kind=runtime.kind,
                contract_version="normalized-inference-0.1.0",
                operations=frozenset({"chat", "stream", "structured_output", "tools"}),
                deployment_id=discovered.deployment_subject.subject_id,
                runtime_endpoint=runtime.endpoint,
                configuration={
                    "model_reference": discovered.runtime_reference,
                    "runtime_owns_template": True,
                },
                allowed_permissions=frozenset(
                    {
                        "network:configured-runtime-endpoint",
                        f"network:{runtime.endpoint}",
                    }
                ),
            )
        )
        if adapter_resolution.adapter is None or adapter_resolution.configuration_digest is None:
            return Part3LifecycleResult(
                "FAILED",
                vertical,
                None,
                None,
                None,
                None,
                None,
                "existing adapter could not be selected/configured",
            )
        adapter_spec = adapter_resolution.adapter
        adapter_subject = SubjectRef(
            SubjectKind.ADAPTER,
            adapter_spec.adapter_id,
            version=adapter_spec.version,
            digest=adapter_spec.artifact_digest,
        )
        environment_attributes = base["configuration"]["values"]["environment"]
        environment_digest = sha256_digest(environment_attributes)
        identity = ModelIdentityReconciler(
            ledger=IdentityLedger(config.identity_ledger_path), clock=self.clock
        ).reconcile(
            IdentityInputs(
                runtime=runtime.subject,
                runtime_kind=runtime.kind,
                runtime_model_reference=discovered.runtime_reference,
                artifact=discovered.artifact_subject,
                deployment=discovered.deployment_subject,
                adapter=adapter_subject,
                configuration_digest=adapter_resolution.configuration_digest,
                environment_digest=environment_digest,
                model_metadata=inspection.details.model_info,
                evidence_ids=tuple(
                    item.evidence_id
                    for item in vertical.discovery.evidence + inspection.evidence
                ),
            )
        )

        attestation = vertical.probes.attestation if vertical.probes else None
        sandbox_outcome = (
            SandboxOutcome.BLOCKED
            if vertical.probes and vertical.probes.problem
            else SandboxOutcome.PASS
            if attestation
            else None
        )
        security = SecurityAssessor().assess(
            isolation_class=IsolationClass.TEST_DOUBLE
            if attestation and "fixture" in attestation.backend_id
            else IsolationClass.REFERENCE_NOT_SECURITY_BOUNDARY,
            sandbox_outcome=sandbox_outcome,
            security_boundary_claimed=False,
            cleanup_complete=attestation.cleanup_complete if attestation else False,
            adapter_trust=TrustState.REVIEW_REQUIRED,
            permissions=(
                f"network:{runtime.endpoint}",
                "filesystem:engine-workspace-only",
            ),
            artifact_manifest_digest=config.artifact_resolution.manifest_digest
            if config.artifact_resolution
            else None,
            identity_collision=identity.alias_collision,
            live_validation=config.vertical_slice.live_validation,
        )

        regression_plan = {
            "id": "regression-plan:part3-default",
            "mandatory_checks": [
                "functional:basic_generation",
                "functional:instruction_following",
                "capability:generation.text",
                "compatibility:overall",
                "configuration:model_binding",
                "risk:security",
            ],
            "expected_configuration_changes": ["model_binding"],
            "fail_closed": True,
        }
        target_snapshot = {
            "id": "target-snapshot:read-only-profile",
            "target_profile_digest": config.vertical_slice.target_profile.profile_digest,
            "capability_snapshot_digest": config.vertical_slice.target_profile.capability_snapshot_digest,
            "source": "read-only-target-profile",
        }
        change_set = {
            "id": "change-set:proposed-model-binding",
            "changes": [
                {
                    "operation": "ADD",
                    "path": "model-bindings/proposed.json",
                    "before": None,
                    "after": base["configuration"]["artifacts"][0]["digest"],
                }
            ],
            "context_paths": ["capability-registry.json", "configuration.json"],
        }
        rollback_plan = {
            "id": "rollback-plan:remove-proposed-binding",
            "method": "restore-content-addressed-target-snapshot",
            "steps": [
                "restore prior configuration",
                "restore prior registry state",
                "remove newly added binding",
                "run mandatory smoke regression",
            ],
            "tested": False,
        }
        policies = {
            "identity": "0.3.0",
            "evidence": "0.3.0",
            "capability": "0.3.0",
            "sandbox": "0.3.0",
            "security": security.policy_version,
            "approval": "0.3.0",
            "regression": "0.3.0",
        }
        proposed = ProposedIntegrationPackageBuilder().build(
            ProposedPackageInput(
                created_at=self.clock(),
                base_package=base,
                identity=identity,
                environment_id=config.vertical_slice.environment.environment_id,
                environment_digest=environment_digest,
                environment_attributes=environment_attributes,
                adapter_id=adapter_spec.adapter_id,
                adapter_artifact_digest=adapter_spec.artifact_digest,
                adapter_configuration_digest=adapter_resolution.configuration_digest,
                adapter_trust=TrustState.REVIEW_REQUIRED.value,
                adapter_resolution=adapter_resolution.disposition.value,
                artifact_resolution=config.artifact_resolution,
                security=security,
                regression_plan=regression_plan,
                target_snapshot=target_snapshot,
                change_set=change_set,
                rollback_plan=rollback_plan,
                permissions=(
                    f"network:{runtime.endpoint}",
                    "filesystem:engine-workspace-only",
                ),
                policy_versions=policies,
            )
        )
        store = ImmutablePackageStore(config.package_store_root)
        submitted = store.submit(proposed)
        approval_request = (
            ApprovalBindingService(store, self.clock).create_request(submitted)
            if config.request_approval
            else None
        )
        return Part3LifecycleResult(
            state="DRAFT_PENDING_APPROVAL",
            vertical_slice=vertical,
            identity=identity,
            security=security,
            proposed_package=proposed,
            submitted_package=submitted,
            approval_request=approval_request,
            problem=None,
        )
