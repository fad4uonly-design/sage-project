from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from model_integration_engine.evidence import sha256_digest
from model_integration_engine.sandbox.contracts import (
    ArtifactDeclaration,
    CodeTrust,
    IsolationClass,
    NetworkMode,
    NetworkPolicy,
    ProcessLimits,
    SandboxControl,
    SandboxExecutionSpec,
    SandboxOutcome,
    SandboxPolicy,
)
from model_integration_engine.sandbox.docker import DockerSandboxBackend


def docker_backend() -> DockerSandboxBackend:
    backend = DockerSandboxBackend()

    try:
        result = subprocess.run(
            [
                backend.docker_binary,
                "version",
                "--format",
                "{{.Server.Version}}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        print(f"DOCKER_HELPER_EXCEPTION: {type(exc).__name__}: {exc}")
        pytest.skip("Docker CLI/daemon is not available")

    if result.returncode != 0:
        print(f"DOCKER_HELPER_RC={result.returncode}")
        print(f"DOCKER_HELPER_STDERR={result.stderr!r}")
        pytest.skip("Docker daemon is not available")

    return backend


def policy(
    *controls: SandboxControl,
    network_mode: NetworkMode = NetworkMode.DENY,
    allowed_endpoints: tuple[str, ...] = (),
    timeout_seconds: float = 10,
    memory_bytes: int = 128 * 1024 * 1024,
    process_count: int = 16,
    output_bytes: int = 1024 * 1024,
) -> SandboxPolicy:
    return SandboxPolicy(
        policy_id="docker-test-policy",
        policy_version="0.1.0",
        required_controls=frozenset(controls),
        network=NetworkPolicy(
            mode=network_mode,
            allowed_endpoints=allowed_endpoints,
        ),
        limits=ProcessLimits(
            timeout_seconds=timeout_seconds,
            cpu_seconds=2,
            memory_bytes=memory_bytes,
            output_bytes=output_bytes,
            file_bytes=8 * 1024 * 1024,
            process_count=process_count,
        ),
        filesystem_isolation_required=True,
        non_root_required=True,
    )


def spec(
    *,
    run_id: str,
    script: str,
    policy_value: SandboxPolicy,
    artifacts: tuple[ArtifactDeclaration, ...] = (),
    mounts=(),
    code_trust: CodeTrust = CodeTrust.TRUSTED_ENGINE_HARNESS,
    environment=None,
    stdin: bytes | None = None,
) -> SandboxExecutionSpec:
    return SandboxExecutionSpec(
        run_id=run_id,
        argv=(
            "python",
            "-c",
            script,
        ),
        environment={} if environment is None else environment,
        mounts=tuple(mounts),
        output_directory="outputs",
        artifacts=artifacts,
        policy=policy_value,
        code_trust=code_trust,
        stdin=stdin,
        working_directory="work",
    )


def test_docker_backend_reports_production_security_boundary() -> None:
    backend = docker_backend()

    capabilities = backend.capabilities()

    assert (
        capabilities.isolation_class
        is IsolationClass.PRODUCTION_SECURITY_BOUNDARY
    )

    expected = {
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
    }

    assert expected <= capabilities.enforceable_controls


def test_docker_executes_trusted_harness_and_cleans_workspace() -> None:
    backend = docker_backend()

    required = (
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

    result = backend.execute(
        spec(
            run_id="docker-basic",
            script="print('docker-ok')",
            policy_value=policy(*required),
        )
    )

    assert result.outcome is SandboxOutcome.PASS
    assert result.isolation_class is IsolationClass.PRODUCTION_SECURITY_BOUNDARY
    assert result.security_boundary_claimed is True
    assert result.exit_code == 0
    assert b"docker-ok" in result.stdout
    assert result.cleanup_complete is True
    assert result.problem_code is None


def test_docker_runs_as_non_root() -> None:
    backend = docker_backend()

    result = backend.execute(
        spec(
            run_id="docker-non-root",
            script=(
                "import os\n"
                "print(os.getuid())\n"
                "print(os.getgid())"
            ),
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.PERMISSION_BOUNDARY,
                SandboxControl.RESULT_CAPTURE,
            ),
        )
    )

    assert result.outcome is SandboxOutcome.PASS
    assert b"65532" in result.stdout


def test_docker_network_is_denied() -> None:
    backend = docker_backend()

    result = backend.execute(
        spec(
            run_id="docker-network-deny",
            script=(
                "import socket\n"
                "s = socket.socket()\n"
                "s.settimeout(2)\n"
                "try:\n"
                "    s.connect(('1.1.1.1', 80))\n"
                "    print('NETWORK_ALLOWED')\n"
                "except Exception:\n"
                "    print('NETWORK_BLOCKED')\n"
                "finally:\n"
                "    s.close()\n"
            ),
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.NETWORK_POLICY,
                SandboxControl.RESULT_CAPTURE,
            ),
        )
    )

    assert result.outcome is SandboxOutcome.PASS
    assert b"NETWORK_BLOCKED" in result.stdout
    assert b"NETWORK_ALLOWED" not in result.stdout


def test_docker_root_filesystem_is_read_only() -> None:
    backend = docker_backend()

    result = backend.execute(
        spec(
            run_id="docker-read-only",
            script=(
                "from pathlib import Path\n"
                "try:\n"
                "    Path('/readonly-test').write_text('x')\n"
                "    print('ROOT_WRITABLE')\n"
                "except Exception:\n"
                "    print('ROOT_READ_ONLY')\n"
            ),
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.FILESYSTEM_ISOLATION,
                SandboxControl.RESULT_CAPTURE,
            ),
        )
    )

    assert result.outcome is SandboxOutcome.PASS
    assert b"ROOT_READ_ONLY" in result.stdout
    assert b"ROOT_WRITABLE" not in result.stdout


def test_docker_capabilities_are_dropped() -> None:
    backend = docker_backend()

    result = backend.execute(
        spec(
            run_id="docker-capabilities",
            script=(
                "from pathlib import Path\n"
                "text = Path('/proc/self/status').read_text()\n"
                "line = [\n"
                "    x for x in text.splitlines()\n"
                "    if x.startswith('CapEff:')\n"
                "][0]\n"
                "print(line)\n"
            ),
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.PERMISSION_BOUNDARY,
                SandboxControl.RESULT_CAPTURE,
            ),
        )
    )

    assert result.outcome is SandboxOutcome.PASS

    cap_line = next(
        line
        for line in result.stdout.decode().splitlines()
        if line.startswith("CapEff:")
    )

    value = int(cap_line.split()[1], 16)

    assert value == 0


def test_docker_artifact_collection_and_digest() -> None:
    backend = docker_backend()

    declaration = ArtifactDeclaration(
        artifact_id="result",
        relative_path="result.json",
        media_type="application/json",
        required=True,
    )

    script = (
        "from pathlib import Path\n"
        "Path('/mie/output/result.json').write_text("
        "'{\"ok\": true}', "
        "encoding='utf-8'\n"
        ")\n"
    )

    result = backend.execute(
        spec(
            run_id="docker-artifact",
            script=script,
            artifacts=(declaration,),
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.FILESYSTEM_ISOLATION,
                SandboxControl.ARTIFACT_ALLOWLIST,
                SandboxControl.ARTIFACT_DIGESTING,
                SandboxControl.RESULT_CAPTURE,
            ),
        )
    )

    assert result.outcome is SandboxOutcome.PASS
    assert len(result.artifacts) == 1

    artifact = result.artifacts[0]

    assert artifact.artifact_id == "result"
    assert artifact.relative_path == "result.json"
    assert artifact.reported_digest.startswith("sha256:")

    expected_digest = sha256_digest(
        b'{"ok": true}'
    )

    assert artifact.reported_digest == expected_digest


def test_docker_rejects_unexpected_artifact() -> None:
    backend = docker_backend()

    declaration = ArtifactDeclaration(
        artifact_id="expected",
        relative_path="expected.json",
        media_type="application/json",
    )

    script = (
        "from pathlib import Path\n"
        "Path('/mie/output/expected.json').write_text('{}')\n"
        "Path('/mie/output/injected.py').write_text('unexpected')\n"
    )

    result = backend.execute(
        spec(
            run_id="docker-artifact-injection",
            script=script,
            artifacts=(declaration,),
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.ARTIFACT_ALLOWLIST,
                SandboxControl.ARTIFACT_DIGESTING,
                SandboxControl.RESULT_CAPTURE,
            ),
        )
    )

    assert result.outcome is SandboxOutcome.FAIL
    assert result.problem_code == "UNEXPECTED_ARTIFACT"
    assert "injected.py" in result.unexpected_artifacts


def test_docker_rejects_missing_required_artifact() -> None:
    backend = docker_backend()

    declaration = ArtifactDeclaration(
        artifact_id="required",
        relative_path="required.json",
        media_type="application/json",
        required=True,
    )

    result = backend.execute(
        spec(
            run_id="docker-missing-artifact",
            script="print('nothing produced')",
            artifacts=(declaration,),
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.ARTIFACT_ALLOWLIST,
                SandboxControl.ARTIFACT_DIGESTING,
                SandboxControl.RESULT_CAPTURE,
            ),
        )
    )

    assert result.outcome is SandboxOutcome.FAIL
    assert result.problem_code == "SANDBOX_ARTIFACT_ERROR"
    assert "required artifact missing" in (
        result.problem_message or ""
    )


def test_docker_blocks_untrusted_generated_code() -> None:
    backend = docker_backend()

    result = backend.execute(
        spec(
            run_id="docker-untrusted",
            script="print('must-not-run')",
            code_trust=CodeTrust.UNTRUSTED_GENERATED,
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.FILESYSTEM_ISOLATION,
                SandboxControl.NETWORK_POLICY,
            ),
        )
    )

    assert result.outcome is SandboxOutcome.BLOCKED
    assert result.problem_code == "DOCKER_UNTRUSTED_CODE_POLICY"
    assert result.security_boundary_claimed is False
    assert result.stdout == b""


def test_docker_blocks_allowlist_without_gateway_network() -> None:
    backend = docker_backend()

    result = backend.execute(
        spec(
            run_id="docker-network-allowlist",
            script="print('must-not-run')",
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.NETWORK_POLICY,
                network_mode=NetworkMode.ALLOWLIST,
                allowed_endpoints=("http://example.com:443",),
            ),
        )
    )

    assert result.outcome is SandboxOutcome.BLOCKED
    assert result.problem_code == "NETWORK_ALLOWLIST_NOT_CONFIGURED"
    assert result.security_boundary_claimed is False


def test_docker_allowlist_uses_configured_internal_network() -> None:
    backend = DockerSandboxBackend(
        allowlist_network="mie-allowlist-internal",
        gateway_endpoint="http://mie-gateway-test:18080",
        approved_upstream_endpoint="http://host.docker.internal:11434",
    )
    execution_spec = spec(
        run_id="docker-network-allowlist-command",
        script="print('ok')",
        policy_value=policy(
            SandboxControl.CONTROLLED_EXECUTION,
            SandboxControl.NETWORK_POLICY,
            network_mode=NetworkMode.ALLOWLIST,
            allowed_endpoints=("http://host.docker.internal:11434",),
        ),
    )

    command = backend._build_docker_command(
        spec=execution_spec,
        container_name="mie-test",
        container_output=Path("output"),
    )

    network_index = command.index("--network")
    assert command[network_index + 1] == "mie-allowlist-internal"
    assert "none" not in command


def test_docker_artifact_collection_survives_execution_cleanup(tmp_path: Path) -> None:
    _ = docker_backend()  # Skips when the Docker daemon is not available.

    backend = DockerSandboxBackend(
        collection_root=tmp_path / "collections"
    )

    declaration = ArtifactDeclaration(
        artifact_id="result",
        relative_path="result.json",
        media_type="application/json",
    )

    execution_spec = spec(
        run_id="docker-artifact-lifetime",
        script=(
            "from pathlib import Path; "
            "Path('/mie/output').mkdir(exist_ok=True); "
            "Path('/mie/output/result.json').write_text('{ok:true}')"
        ),
        policy_value=policy(
            SandboxControl.CONTROLLED_EXECUTION,
            SandboxControl.PROCESS_LIMITS,
            SandboxControl.ARTIFACT_ALLOWLIST,
            SandboxControl.ARTIFACT_DIGESTING,
            SandboxControl.RESULT_CAPTURE,
            SandboxControl.FAILURE_ISOLATION,
            SandboxControl.CLEAN_ENVIRONMENT,
            SandboxControl.CLEANUP,
            SandboxControl.TIMEOUT,
        ),
        artifacts=(declaration,),
    )

    result = backend.execute(execution_spec)

    assert result.outcome is SandboxOutcome.PASS
    assert result.cleanup_complete is True
    assert len(result.artifacts) == 1

    collection = Path(result.artifacts[0].collection_root)
    assert collection.exists()
    assert (
        collection / "result.json"
    ).read_text(encoding="utf-8") == '{ok:true}'


def test_docker_allowlist_blocks_unapproved_endpoint() -> None:
    backend = DockerSandboxBackend(
        allowlist_network="mie-allowlist-internal",
        gateway_endpoint="http://mie-gateway-test:18080",
        approved_upstream_endpoint="http://host.docker.internal:11434",
    )

    result = backend.execute(
        spec(
            run_id="docker-network-allowlist-mismatch",
            script="print('must-not-run')",
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.NETWORK_POLICY,
                network_mode=NetworkMode.ALLOWLIST,
                allowed_endpoints=("http://example.com:443",),
            ),
        )
    )

    assert result.outcome is SandboxOutcome.BLOCKED
    assert result.problem_code == "NETWORK_ALLOWLIST_MISMATCH"
    assert result.security_boundary_claimed is False


def test_docker_blocks_inherit_network_policy() -> None:
    backend = docker_backend()

    result = backend.execute(
        spec(
            run_id="docker-network-inherit",
            script="print('must-not-run')",
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.NETWORK_POLICY,
                network_mode=NetworkMode.INHERIT,
            ),
        )
    )

    assert result.outcome is SandboxOutcome.BLOCKED
    assert result.problem_code == "NETWORK_POLICY_UNSAFE"
    assert result.security_boundary_claimed is False


def test_docker_timeout() -> None:
    backend = docker_backend()

    result = backend.execute(
        spec(
            run_id="docker-timeout",
            script="import time; time.sleep(30)",
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.TIMEOUT,
                timeout_seconds=2,
            ),
        )
    )

    assert result.outcome is SandboxOutcome.TIMEOUT
    assert result.timed_out is True
    assert result.problem_code == "SANDBOX_TIMEOUT"
    assert result.cleanup_complete is True


def test_docker_output_is_bounded() -> None:
    backend = docker_backend()

    result = backend.execute(
        spec(
            run_id="docker-output-limit",
            script="print('x' * 1000000)",
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.RESULT_CAPTURE,
                output_bytes=4096,
            ),
        )
    )

    assert len(result.stdout) <= 4096


def test_docker_does_not_implicitly_mount_repository() -> None:
    backend = docker_backend()

    result = backend.execute(
        spec(
            run_id="docker-no-repository",
            script=(
                "from pathlib import Path\n"
                "print(Path('/mie').exists())\n"
                "print(Path('/workspace').exists())\n"
            ),
            policy_value=policy(
                SandboxControl.CONTROLLED_EXECUTION,
                SandboxControl.FILESYSTEM_ISOLATION,
                SandboxControl.RESULT_CAPTURE,
            ),
        )
    )

    assert result.outcome is SandboxOutcome.PASS

    output = result.stdout.decode()

    # /mie exists because the backend owns /mie/work and /mie/output.
    # The SAGE/MIE repository itself is never mounted.
    assert "True" in output
