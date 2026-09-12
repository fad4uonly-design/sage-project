from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from model_integration_engine.application.probe_backend import (
    DockerProbeExecutionBackend,
)
from model_integration_engine.application.probes import ProbePlan
from model_integration_engine.domain import SubjectKind, SubjectRef
from model_integration_engine.evidence import sha256_digest
from model_integration_engine.sandbox.contracts import (
    IsolationClass,
    SandboxExecutionResultV3,
    SandboxOutcome,
)

from tests.phase2_support import operation_context


class CapturingSandbox:
    backend_id = "mie.sandbox.docker"
    gateway_endpoint = "http://mie-gateway-test:18080"
    approved_upstream_endpoint = "http://host.docker.internal:11434"

    def __init__(self) -> None:
        self.spec = None

    def execute(self, spec):
        self.spec = spec
        return SandboxExecutionResultV3(
            run_id=spec.run_id,
            backend_id=self.backend_id,
            backend_version="test",
            isolation_class=IsolationClass.PRODUCTION_SECURITY_BOUNDARY,
            outcome=SandboxOutcome.BLOCKED,
            requested_controls=frozenset(spec.policy.required_controls),
            enforced_controls=frozenset(),
            missing_controls=frozenset(spec.policy.required_controls),
            started_at=operation_context().deadline,
            completed_at=operation_context().deadline,
            exit_code=None,
            timed_out=False,
            stdout=b"",
            stderr=b"",
            stdout_digest=sha256_digest(b""),
            stderr_digest=sha256_digest(b""),
            artifacts=(),
            unexpected_artifacts=(),
            resource_usage={},
            cleanup_complete=True,
            security_boundary_claimed=False,
            problem_code="TEST_BLOCKED",
            problem_message="Test sandbox intentionally blocks execution.",
        )


def test_docker_probe_backend_separates_worker_gateway_from_approved_upstream(
    tmp_path: Path,
) -> None:
    sandbox = CapturingSandbox()

    adapter = SimpleNamespace(
        client=SimpleNamespace(
            endpoint="http://adapter-endpoint-must-not-be-used:9999"
        ),
        config=SimpleNamespace(
            model_reference="test-model",
            runtime_owns_template=True,
        ),
    )

    runtime = SubjectRef(
        SubjectKind.RUNTIME,
        "runtime:test",
        digest=sha256_digest("runtime"),
    )
    deployment = SubjectRef(
        SubjectKind.DEPLOYMENT,
        "deployment:test",
        digest=sha256_digest("deployment"),
    )

    plan = ProbePlan(
        plan_id="probe-plan:test",
        suite_id="mie.safe-vertical-slice",
        suite_version="0.2.0",
        deployment=deployment,
        runtime=runtime,
        adapter_id="mie.adapter.ollama-chat",
        configuration_digest=sha256_digest("config"),
        environment_id="env:test",
        cases=(),
        required_controls=("network_allowlist",),
    )

    backend = DockerProbeExecutionBackend(
        sandbox=sandbox,
        worker_source=str(
            Path("src/model_integration_engine").resolve()
        ),
        artifact_store_root=tmp_path / "artifacts",
    )

    import asyncio

    batch = asyncio.run(
        backend.execute(
            plan=plan,
            harness=None,
            adapter=adapter,
            context=operation_context(),
        )
    )

    assert sandbox.spec is not None

    worker_document = json.loads(
        sandbox.spec.stdin.decode("utf-8")
    )

    assert (
        worker_document["runtime_locator"]
        == "http://mie-gateway-test:18080"
    )

    assert (
        sandbox.spec.policy.network.allowed_endpoints
        == ("http://host.docker.internal:11434",)
    )

    assert (
        batch.attestation.allowed_endpoints
        == ("http://host.docker.internal:11434",)
    )

    assert (
        worker_document["runtime_locator"]
        != adapter.client.endpoint
    )
