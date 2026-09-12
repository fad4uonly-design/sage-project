from __future__ import annotations

import sys
from pathlib import Path

import pytest
from model_integration_engine.sandbox.contracts import (
    ArtifactDeclaration,
    CodeTrust,
    NetworkMode,
    NetworkPolicy,
    ProcessLimits,
    SandboxControl,
    SandboxExecutionSpec,
    SandboxOutcome,
    SandboxPolicy,
)
from model_integration_engine.sandbox.docker import DockerSandboxBackend


def make_policy(
    *controls: SandboxControl,
) -> SandboxPolicy:
    return SandboxPolicy(
        policy_id="docker-test-policy",
        policy_version="0.3.0",
        required_controls=frozenset(controls),
        network=NetworkPolicy(NetworkMode.DENY),
        limits=ProcessLimits(
            timeout_seconds=10,
            cpu_seconds=2,
            memory_bytes=256 * 1024 * 1024,
            output_bytes=1024 * 1024,
            file_bytes=1024 * 1024,
            process_count=16,
        ),
        filesystem_isolation_required=True,
        non_root_required=True,
    )


def required_controls() -> tuple[SandboxControl, ...]:
    return (
        SandboxControl.CONTROLLED_EXECUTION,
        SandboxControl.FILESYSTEM_ISOLATION,
        SandboxControl.NETWORK_POLICY,
        SandboxControl.PROCESS_LIMITS,
        SandboxControl.PERMISSION_BOUNDARY,
        SandboxControl.ARTIFACT_ALLOWLIST,
        SandboxControl.ARTIFACT_DIGESTING,
        SandboxControl.RESULT_CAPTURE,
        SandboxControl.FAILURE_ISOLATION,
        SandboxControl.CLEAN_ENVIRONMENT,
        SandboxControl.CLEANUP,
        SandboxControl.TIMEOUT,
    )


def docker_available() -> bool:
    import shutil
    import subprocess

    docker_binary = shutil.which("docker")
    if docker_binary is None:
        return False

    try:
        result = subprocess.run(
            [docker_binary, "version", "--format", "{{.Server.Version}}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False

    return result.returncode == 0


def test_docker_backend_capabilities() -> None:
    backend = DockerSandboxBackend()

    capabilities = backend.capabilities()

    assert capabilities.backend_id == "mie.sandbox.docker"
    assert capabilities.isolation_class.value == (
        "PRODUCTION_SECURITY_BOUNDARY"
    )

    assert set(required_controls()).issubset(
        capabilities.enforceable_controls
    )


def test_docker_blocks_untrusted_generated_code(tmp_path: Path) -> None:
    backend = DockerSandboxBackend()

    spec = SandboxExecutionSpec(
        run_id="docker-untrusted",
        argv=(sys.executable, "-c", "print('must not execute')"),
        environment={},
        mounts=(),
        output_directory="output",
        artifacts=(),
        policy=make_policy(*required_controls()),
        code_trust=CodeTrust.UNTRUSTED_GENERATED,
    )

    result = backend.execute(spec)

    assert result.outcome is SandboxOutcome.BLOCKED
    assert result.problem_code == "DOCKER_UNTRUSTED_CODE_POLICY"
    assert result.security_boundary_claimed is False


def test_docker_executes_trusted_harness_when_available() -> None:
    if not docker_available():
        pytest.skip("Docker daemon is not available")

    backend = DockerSandboxBackend()

    spec = SandboxExecutionSpec(
        run_id="docker-basic-execution",
        argv=(
            "python",
            "-c",
            "print('docker-ok')",
        ),
        environment={},
        mounts=(),
        output_directory="output",
        artifacts=(),
        policy=make_policy(*required_controls()),
        code_trust=CodeTrust.TRUSTED_ENGINE_HARNESS,
    )

    result = backend.execute(spec)

    assert result.outcome is SandboxOutcome.PASS
    assert result.exit_code == 0
    assert b"docker-ok" in result.stdout
    assert result.security_boundary_claimed is True
    assert result.cleanup_complete is True


def test_docker_network_is_denied() -> None:
    if not docker_available():
        pytest.skip("Docker daemon is not available")

    backend = DockerSandboxBackend()

    spec = SandboxExecutionSpec(
        run_id="docker-network-deny",
        argv=(
            "python",
            "-c",
            (
                "import socket; "
                "s=socket.socket(); "
                "s.settimeout(2); "
                "s.connect(('1.1.1.1', 80))"
            ),
        ),
        environment={},
        mounts=(),
        output_directory="output",
        artifacts=(),
        policy=make_policy(
            SandboxControl.CONTROLLED_EXECUTION,
            SandboxControl.NETWORK_POLICY,
            SandboxControl.PROCESS_LIMITS,
            SandboxControl.PERMISSION_BOUNDARY,
            SandboxControl.FILESYSTEM_ISOLATION,
            SandboxControl.RESULT_CAPTURE,
            SandboxControl.FAILURE_ISOLATION,
            SandboxControl.CLEAN_ENVIRONMENT,
            SandboxControl.CLEANUP,
            SandboxControl.TIMEOUT,
            SandboxControl.ARTIFACT_ALLOWLIST,
            SandboxControl.ARTIFACT_DIGESTING,
        ),
        code_trust=CodeTrust.TRUSTED_ENGINE_HARNESS,
    )

    result = backend.execute(spec)

    assert result.outcome is SandboxOutcome.FAIL
    assert result.exit_code != 0
    assert result.security_boundary_claimed is True


def test_docker_captures_declared_artifact() -> None:
    if not docker_available():
        pytest.skip("Docker daemon is not available")

    backend = DockerSandboxBackend()

    declaration = ArtifactDeclaration(
        artifact_id="result",
        relative_path="result.json",
        media_type="application/json",
        required=True,
        max_bytes=1024,
    )

    script = (
        "from pathlib import Path; "
        "Path('/mie/output/result.json').write_text('{\"ok\": true}')"
    )

    spec = SandboxExecutionSpec(
        run_id="docker-artifact",
        argv=("python", "-c", script),
        environment={},
        mounts=(),
        output_directory="output",
        artifacts=(declaration,),
        policy=make_policy(*required_controls()),
        code_trust=CodeTrust.TRUSTED_ENGINE_HARNESS,
    )

    result = backend.execute(spec)

    assert result.outcome is SandboxOutcome.PASS
    assert len(result.artifacts) == 1

    artifact = result.artifacts[0]

    assert artifact.artifact_id == "result"
    assert artifact.relative_path == "result.json"
    assert artifact.reported_digest.startswith("sha256:")


def test_docker_rejects_unexpected_artifact() -> None:
    if not docker_available():
        pytest.skip("Docker daemon is not available")

    backend = DockerSandboxBackend()

    script = (
        "from pathlib import Path; "
        "Path('/mie/output/unexpected.txt').write_text('unexpected')"
    )

    spec = SandboxExecutionSpec(
        run_id="docker-unexpected-artifact",
        argv=("python", "-c", script),
        environment={},
        mounts=(),
        output_directory="output",
        artifacts=(),
        policy=make_policy(*required_controls()),
        code_trust=CodeTrust.TRUSTED_ENGINE_HARNESS,
    )

    result = backend.execute(spec)

    assert result.outcome is SandboxOutcome.FAIL
    assert result.problem_code == "UNEXPECTED_ARTIFACT"
    assert "unexpected.txt" in result.unexpected_artifacts


def test_docker_read_only_root_filesystem() -> None:
    if not docker_available():
        pytest.skip("Docker daemon is not available")

    backend = DockerSandboxBackend()

    spec = SandboxExecutionSpec(
        run_id="docker-readonly-root",
        argv=(
            "python",
            "-c",
            (
                "from pathlib import Path; "
                "Path('/readonly-test.txt').write_text('should fail')"
            ),
        ),
        environment={},
        mounts=(),
        output_directory="output",
        artifacts=(),
        policy=make_policy(*required_controls()),
        code_trust=CodeTrust.TRUSTED_ENGINE_HARNESS,
    )

    result = backend.execute(spec)

    assert result.outcome is SandboxOutcome.FAIL
    assert result.exit_code != 0
    assert result.security_boundary_claimed is True
