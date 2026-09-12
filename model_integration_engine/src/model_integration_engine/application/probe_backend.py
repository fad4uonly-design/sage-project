from __future__ import annotations

import json
from pathlib import Path

from ..contracts import OperationContext, RuntimeAdapter
from ..evidence import deterministic_id, sha256_digest
from ..sandbox.artifacts import SecureArtifactResolver
from ..sandbox.contracts import (
    ArtifactDeclaration,
    CodeTrust,
    NetworkMode,
    NetworkPolicy,
    ProcessLimits,
    SandboxControl,
    SandboxExecutionSpec,
    SandboxMount,
    SandboxPolicy,
)
from ..sandbox.docker import DockerSandboxBackend
from ..sandbox.probe_artifacts import ProbeArtifactIngestor
from ..sandbox.probe_worker_contract import ProbeWorkerContextSpec, ProbeWorkerSpec
from .probes import (
    BackendProbeBatch,
    IsolationAttestation,
    ProbeExecutionBackend,
    ProbePlan,
    SafeProbeHarness,
)


class DockerProbeExecutionBackend(ProbeExecutionBackend):
    backend_id = "mie.probes.docker"
    backend_version = "0.1.0"

    def __init__(
        self,
        *,
        sandbox: DockerSandboxBackend,
        worker_source: str,
        artifact_store_root: str | Path,
    ) -> None:
        self.sandbox = sandbox
        self.worker_source = str(Path(worker_source).resolve())
        self.artifact_store_root = Path(artifact_store_root).resolve()
        self.artifact_store_root.mkdir(parents=True, exist_ok=True)

    async def execute(
        self,
        plan: ProbePlan,
        harness: SafeProbeHarness,
        adapter: RuntimeAdapter,
        context: OperationContext,
    ) -> BackendProbeBatch:
        del harness

        run_id = deterministic_id("probe-run", plan.plan_id, context.run_id)

        adapter_config = getattr(adapter, "config", None)
        client = getattr(adapter, "client", None)
        if adapter_config is None or client is None:
            raise ValueError("Probe adapter must expose config and client")

        worker_runtime_locator = self.sandbox.gateway_endpoint
        approved_upstream_endpoint = self.sandbox.approved_upstream_endpoint

        if worker_runtime_locator is None:
            raise ValueError("Docker sandbox gateway endpoint is not configured")

        if approved_upstream_endpoint is None:
            raise ValueError(
                "Docker sandbox approved upstream endpoint is not configured"
            )

        worker_context = ProbeWorkerContextSpec(
            run_id=run_id,
            correlation_id=context.correlation_id,
            deadline=context.deadline,
            policy_id=context.policy_id,
            policy_version=context.policy_version,
            workspace_id=context.workspace_id,
            allowed_permissions=context.allowed_permissions,
            limits=context.limits,
        )

        worker_spec = ProbeWorkerSpec.create(
            run_id=run_id,
            runtime_locator=worker_runtime_locator,
            adapter_id=plan.adapter_id,
            adapter_configuration={
                "runtime": plan.runtime.subject_id,
                "deployment": plan.deployment.subject_id,
                "model_reference": adapter_config.model_reference,
                "configuration_digest": plan.configuration_digest,
                "runtime_owns_template": adapter_config.runtime_owns_template,
            },
            plan=plan,
            context=worker_context,
            output_artifact_path="/mie/output/probe-results.json",
        )

        control_map = {
            "read_only_inputs": SandboxControl.FILESYSTEM_ISOLATION,
            "ephemeral_scratch": SandboxControl.FILESYSTEM_ISOLATION,
            "network_allowlist": SandboxControl.NETWORK_POLICY,
            "no_target_mount": SandboxControl.FILESYSTEM_ISOLATION,
            "resource_limits": SandboxControl.PROCESS_LIMITS,
        }
        try:
            sandbox_controls = frozenset(
                control_map[name] for name in plan.required_controls
            )
        except KeyError as exc:
            raise ValueError(
                f"Unsupported probe sandbox control: {exc.args[0]}"
            ) from exc

        policy = SandboxPolicy(
            policy_id=context.policy_id,
            policy_version=context.policy_version,
            required_controls=sandbox_controls,
            network=NetworkPolicy(
                mode=NetworkMode.ALLOWLIST,
                allowed_endpoints=(approved_upstream_endpoint,),
            ),
            limits=ProcessLimits(
                timeout_seconds=context.limits.timeout_seconds,
                memory_bytes=context.limits.max_memory_bytes,
                output_bytes=context.limits.max_output_bytes,
                process_count=context.limits.max_processes,
            ),
        )

        spec = SandboxExecutionSpec(
            run_id=run_id,
            argv=(
                "python",
                "-m",
                "model_integration_engine.sandbox.probe_worker",
            ),
            environment={"PYTHONPATH": "/app"},
            mounts=(
                SandboxMount(
                    source=self.worker_source,
                    destination="app",
                    read_only=True,
                ),
            ),
            output_directory="output",
            artifacts=(
                ArtifactDeclaration(
                    artifact_id="probe-results",
                    relative_path="probe-results.json",
                    media_type="application/vnd.mie.probe-results+json",
                    required=True,
                ),
            ),
            policy=policy,
            code_trust=CodeTrust.TRUSTED_ENGINE_HARNESS,
            stdin=json.dumps(
                worker_spec.to_document(),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
        )

        sandbox_result = self.sandbox.execute(spec)

        passed = sandbox_result.outcome.value == "PASS"
        attestation = IsolationAttestation(
            run_id=run_id,
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            job_digest=sha256_digest(
                {
                    "plan_id": plan.plan_id,
                    "worker_digest": worker_spec.digest,
                    "sandbox_backend": sandbox_result.backend_id,
                    "sandbox_job_digest": sandbox_result.stdout_digest,
                }
            ),
            isolated=(
                passed
                and sandbox_result.security_boundary_claimed
                and not sandbox_result.missing_controls
            ),
            requested_controls=plan.required_controls,
            enforced_controls=plan.required_controls if passed else (),
            missing_controls=() if passed else plan.required_controls,
            allowed_endpoints=(approved_upstream_endpoint,),
            started_at=sandbox_result.started_at,
            completed_at=sandbox_result.completed_at,
            host_write_observed=False,
            cleanup_complete=sandbox_result.cleanup_complete,
        )

        if not passed:
            return BackendProbeBatch(results=(), attestation=attestation)

        if len(sandbox_result.artifacts) != 1:
            raise RuntimeError("Probe sandbox did not return exactly one result artifact")

        candidate = sandbox_result.artifacts[0]
        resolver = SecureArtifactResolver(self.artifact_store_root)
        resolution = resolver.resolve(
            collection_root=Path(candidate.collection_root),
            declarations=spec.artifacts,
            candidates=sandbox_result.artifacts,
            run_id=run_id,
        )

        artifact = resolution.artifacts[0]
        results = ProbeArtifactIngestor().ingest(
            artifact=artifact,
            resolver=resolver,
            expected_plan=plan,
            expected_run_id=run_id,
        )

        return BackendProbeBatch(
            results=results,
            attestation=attestation,
        )





