from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from ..domain import JSONValue
from ..evidence import sha256_digest
from .contracts import (
    CodeTrust,
    CollectedArtifactCandidate,
    IsolationClass,
    NetworkMode,
    ProductionSandboxBackend,
    SandboxCapabilitiesV3,
    SandboxControl,
    SandboxExecutionResultV3,
    SandboxExecutionSpec,
    SandboxOutcome,
)


class DockerSandboxBackend(ProductionSandboxBackend):
    """
    Production sandbox backend using Docker/OCI isolation.

    Security boundary:
      - read-only container root filesystem
      - dedicated writable tmpfs areas
      - fixed non-root UID/GID
      - all Linux capabilities dropped
      - no-new-privileges
      - explicit network policy
      - CPU / memory / PID limits
      - bounded stdout/stderr
      - timeout enforcement
      - explicit artifact allowlist
      - artifact SHA-256 digesting
      - isolated temporary execution workspace
      - deterministic container cleanup

    Network ALLOWLIST requires an explicitly configured internal gateway network.
    INHERIT remains fail-closed.
    """

    backend_id = "mie.sandbox.docker"
    backend_version = "0.1.10"

    docker_binary = "docker"

    image = "python:3.14-slim"

    container_uid = 65532
    container_gid = 65532

    def __init__(
        self,
        *,
        allowlist_network: str | None = None,
        gateway_endpoint: str | None = None,
        approved_upstream_endpoint: str | None = None,
        collection_root: str | Path | None = None,
    ) -> None:
        network = allowlist_network.strip() if allowlist_network else None
        gateway = gateway_endpoint.strip().rstrip("/") if gateway_endpoint else None
        upstream = (
            approved_upstream_endpoint.strip().rstrip("/")
            if approved_upstream_endpoint
            else None
        )

        if network == "":
            network = None
        if gateway == "":
            gateway = None
        if upstream == "":
            upstream = None

        if gateway is not None:
            parsed = urlsplit(gateway)
            if parsed.scheme != "http" or not parsed.netloc:
                raise ValueError(
                    "gateway_endpoint must be an absolute http URL"
                )
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError(
                    "gateway_endpoint must not include a path, query, or fragment"
                )

        if upstream is not None:
            parsed = urlsplit(upstream)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(
                    "approved_upstream_endpoint must be an absolute http(s) URL"
                )
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError(
                    "approved_upstream_endpoint must not include a path, query, or fragment"
                )

        self.allowlist_network = network
        self.gateway_endpoint = gateway
        self.approved_upstream_endpoint = upstream
        self.collection_root = (
            Path(collection_root).resolve()
            if collection_root is not None
            else None
        )
        if self.collection_root is not None:
            self.collection_root.mkdir(parents=True, exist_ok=True)

    def capabilities(self) -> SandboxCapabilitiesV3:
        return SandboxCapabilitiesV3(
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            isolation_class=IsolationClass.PRODUCTION_SECURITY_BOUNDARY,
            enforceable_controls=frozenset(
                {
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
            ),
            notes=(
                "Docker/OCI isolation is used as the production sandbox boundary.",
                "Root filesystem is mounted read-only.",
                "Execution uses a fixed non-root numeric UID/GID.",
                "Linux capabilities are dropped.",
                "no-new-privileges is enabled.",
                "Network DENY is enforced with Docker network=none.",
                "Network ALLOWLIST uses an explicitly configured internal gateway network.",
                "INHERIT network mode is forbidden.",
                "Writable state is restricted to dedicated temporary mounts.",
                "CPU, memory, PID and timeout controls are enforced.",
                "Only explicitly declared artifacts are accepted.",
                "Container output is copied before container cleanup.",
            ),
        )

    def execute(self, spec: SandboxExecutionSpec) -> SandboxExecutionResultV3:
        started_at = datetime.now(UTC)

        requested = frozenset(spec.policy.required_controls)

        # ------------------------------------------------------------
        # Pre-execution policy validation.
        # ------------------------------------------------------------

        if spec.code_trust is CodeTrust.UNTRUSTED_GENERATED:
            return self._blocked_result(
                spec=spec,
                started_at=started_at,
                requested=requested,
                problem_code="DOCKER_UNTRUSTED_CODE_POLICY",
                problem_message=(
                    "Untrusted generated code is not permitted by the "
                    "production Docker sandbox policy."
                ),
            )

        if spec.policy.network.mode is NetworkMode.ALLOWLIST:
            configured = (
                self.allowlist_network is not None
                and self.gateway_endpoint is not None
                and self.approved_upstream_endpoint is not None
            )
            if not configured:
                return self._blocked_result(
                    spec=spec,
                    started_at=started_at,
                    requested=requested,
                    problem_code="NETWORK_ALLOWLIST_NOT_CONFIGURED",
                    problem_message=(
                        "Docker allowlist networking requires an explicitly "
                        "configured internal gateway network, gateway endpoint, "
                        "and approved upstream endpoint."
                    ),
                )

            requested_endpoints = tuple(
                endpoint.strip().rstrip("/")
                for endpoint in spec.policy.network.allowed_endpoints
            )
            if requested_endpoints != (self.approved_upstream_endpoint,):
                return self._blocked_result(
                    spec=spec,
                    started_at=started_at,
                    requested=requested,
                    problem_code="NETWORK_ALLOWLIST_MISMATCH",
                    problem_message=(
                        "The requested endpoint allowlist does not exactly match "
                        "the backend's configured approved upstream endpoint."
                    ),
                )

        if spec.policy.network.mode is NetworkMode.INHERIT:
            return self._blocked_result(
                spec=spec,
                started_at=started_at,
                requested=requested,
                problem_code="NETWORK_POLICY_UNSAFE",
                problem_message=(
                    "INHERIT network mode is forbidden for production "
                    "sandbox execution."
                ),
            )

        missing = requested - self.capabilities().enforceable_controls

        if missing:
            return self._blocked_result(
                spec=spec,
                started_at=started_at,
                requested=requested,
                problem_code="SANDBOX_REQUIRED_CONTROLS_UNAVAILABLE",
                problem_message=(
                    "Requested sandbox controls cannot be enforced: "
                    + ", ".join(
                        sorted(control.value for control in missing)
                    )
                ),
            )

        run_root: Path | None = None

        container_name = (
            f"mie-{self._safe_run_id(spec.run_id)}"
        )

        stdout = b""
        stderr = b""
        exit_code: int | None = None
        timed_out = False

        artifacts: tuple[
            CollectedArtifactCandidate, ...
        ] = ()

        unexpected_artifacts: tuple[str, ...] = ()


        resource_usage: dict[str, JSONValue] = {}

        process: subprocess.Popen[bytes] | None = None

        try:
            run_root = Path(
                tempfile.mkdtemp(prefix="mie-docker-")
            )

            output_dir = run_root / "output"

            output_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            container_output = run_root / "container_output"

            container_output.mkdir(
                parents=True,
                exist_ok=True,
            )

            command = self._build_docker_command(
                spec=spec,
                container_name=container_name,
                container_output=container_output,
            )

            process = subprocess.Popen(
                command,
                stdin=(
                    subprocess.PIPE
                    if spec.stdin is not None
                    else None
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # --------------------------------------------------------
            # Execute Docker.
            # --------------------------------------------------------

            try:
                raw_stdout, raw_stderr = process.communicate(
                    input=spec.stdin,
                    timeout=spec.policy.limits.timeout_seconds,
                )

                exit_code = process.returncode

            except subprocess.TimeoutExpired as exc:
                timed_out = True

                self._docker_stop(container_name)

                with contextlib.suppress(OSError):
                    process.kill()

                raw_stdout, raw_stderr = process.communicate()

                stdout = self._bound_output(
                    (
                        raw_stdout
                        if raw_stdout is not None
                        else exc.stdout
                    ),
                    spec.policy.limits.output_bytes,
                )

                stderr = self._bound_output(
                    (
                        raw_stderr
                        if raw_stderr is not None
                        else exc.stderr
                    ),
                    spec.policy.limits.output_bytes,
                )

                completed_at = datetime.now(UTC)

                return SandboxExecutionResultV3(
                    run_id=spec.run_id,
                    backend_id=self.backend_id,
                    backend_version=self.backend_version,
                    isolation_class=(
                        IsolationClass.PRODUCTION_SECURITY_BOUNDARY
                    ),
                    outcome=SandboxOutcome.TIMEOUT,
                    requested_controls=requested,
                    enforced_controls=requested,
                    missing_controls=frozenset(),
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=None,
                    timed_out=True,
                    stdout=stdout,
                    stderr=stderr,
                    stdout_digest=sha256_digest(stdout),
                    stderr_digest=sha256_digest(stderr),
                    artifacts=(),
                    unexpected_artifacts=(),
                    resource_usage={
                        "stdout_bytes_retained": len(stdout),
                        "stderr_bytes_retained": len(stderr),
                    },
                    cleanup_complete=True,
                    security_boundary_claimed=True,
                    problem_code="SANDBOX_TIMEOUT",
                    problem_message=(
                        "Docker execution exceeded the sandbox timeout."
                    ),
                )

            stdout = self._bound_output(
                raw_stdout,
                spec.policy.limits.output_bytes,
            )

            stderr = self._bound_output(
                raw_stderr,
                spec.policy.limits.output_bytes,
            )

            resource_usage = {
                "stdout_bytes_retained": len(stdout),
                "stderr_bytes_retained": len(stderr),
            }

            # --------------------------------------------------------
            # IMPORTANT:
            #
            # Docker container is NOT removed yet.
            #
            # We must copy /mie/output before cleanup.
            # --------------------------------------------------------

            try:
                self._copy_container_output(
                    container_name=container_name,
                    output_dir=output_dir,
                )

            except DockerOutputCollectionError as exc:
                completed_at = datetime.now(UTC)

                return SandboxExecutionResultV3(
                    run_id=spec.run_id,
                    backend_id=self.backend_id,
                    backend_version=self.backend_version,
                    isolation_class=(
                        IsolationClass.PRODUCTION_SECURITY_BOUNDARY
                    ),
                    outcome=SandboxOutcome.FAIL,
                    requested_controls=requested,
                    enforced_controls=requested,
                    missing_controls=frozenset(),
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=exit_code,
                    timed_out=False,
                    stdout=stdout,
                    stderr=stderr,
                    stdout_digest=sha256_digest(stdout),
                    stderr_digest=sha256_digest(stderr),
                    artifacts=(),
                    unexpected_artifacts=(),
                    resource_usage=resource_usage,
                    cleanup_complete=False,
                    security_boundary_claimed=True,
                    problem_code=exc.code,
                    problem_message=str(exc),
                )

            # --------------------------------------------------------
            # Artifact validation.
            # --------------------------------------------------------

            try:
                (
                    artifacts,
                    unexpected_artifacts,
                ) = self._collect_artifacts(
                    spec=spec,
                    output_dir=output_dir,
                )

            except UnexpectedArtifactError as exc:
                completed_at = datetime.now(UTC)

                return SandboxExecutionResultV3(
                    run_id=spec.run_id,
                    backend_id=self.backend_id,
                    backend_version=self.backend_version,
                    isolation_class=(
                        IsolationClass.PRODUCTION_SECURITY_BOUNDARY
                    ),
                    outcome=SandboxOutcome.FAIL,
                    requested_controls=requested,
                    enforced_controls=requested,
                    missing_controls=frozenset(),
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=exit_code,
                    timed_out=False,
                    stdout=stdout,
                    stderr=stderr,
                    stdout_digest=sha256_digest(stdout),
                    stderr_digest=sha256_digest(stderr),
                    artifacts=(),
                    unexpected_artifacts=exc.paths,
                    resource_usage=resource_usage,
                    cleanup_complete=False,
                    security_boundary_claimed=True,
                    problem_code="UNEXPECTED_ARTIFACT",
                    problem_message=(
                        "Unexpected artifacts were produced: "
                        + ", ".join(exc.paths)
                    ),
                )

            except ArtifactCollectionError as exc:
                completed_at = datetime.now(UTC)

                return SandboxExecutionResultV3(
                    run_id=spec.run_id,
                    backend_id=self.backend_id,
                    backend_version=self.backend_version,
                    isolation_class=(
                        IsolationClass.PRODUCTION_SECURITY_BOUNDARY
                    ),
                    outcome=SandboxOutcome.FAIL,
                    requested_controls=requested,
                    enforced_controls=requested,
                    missing_controls=frozenset(),
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=exit_code,
                    timed_out=False,
                    stdout=stdout,
                    stderr=stderr,
                    stdout_digest=sha256_digest(stdout),
                    stderr_digest=sha256_digest(stderr),
                    artifacts=artifacts,
                    unexpected_artifacts=unexpected_artifacts,
                    resource_usage=resource_usage,
                    cleanup_complete=False,
                    security_boundary_claimed=True,
                    problem_code=exc.code,
                    problem_message=str(exc),
                )

            # --------------------------------------------------------
            # Process exit status.
            # --------------------------------------------------------

            if exit_code != 0:
                completed_at = datetime.now(UTC)

                return SandboxExecutionResultV3(
                    run_id=spec.run_id,
                    backend_id=self.backend_id,
                    backend_version=self.backend_version,
                    isolation_class=(
                        IsolationClass.PRODUCTION_SECURITY_BOUNDARY
                    ),
                    outcome=SandboxOutcome.FAIL,
                    requested_controls=requested,
                    enforced_controls=requested,
                    missing_controls=frozenset(),
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=exit_code,
                    timed_out=False,
                    stdout=stdout,
                    stderr=stderr,
                    stdout_digest=sha256_digest(stdout),
                    stderr_digest=sha256_digest(stderr),
                    artifacts=artifacts,
                    unexpected_artifacts=unexpected_artifacts,
                    resource_usage=resource_usage,
                    cleanup_complete=False,
                    security_boundary_claimed=True,
                    problem_code="SANDBOX_PROCESS_FAILED",
                    problem_message=(
                        f"Docker process exited with code {exit_code}."
                    ),
                )

            # --------------------------------------------------------
            # Unexpected artifacts.
            # --------------------------------------------------------

            if unexpected_artifacts:
                completed_at = datetime.now(UTC)

                return SandboxExecutionResultV3(
                    run_id=spec.run_id,
                    backend_id=self.backend_id,
                    backend_version=self.backend_version,
                    isolation_class=(
                        IsolationClass.PRODUCTION_SECURITY_BOUNDARY
                    ),
                    outcome=SandboxOutcome.FAIL,
                    requested_controls=requested,
                    enforced_controls=requested,
                    missing_controls=frozenset(),
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=exit_code,
                    timed_out=False,
                    stdout=stdout,
                    stderr=stderr,
                    stdout_digest=sha256_digest(stdout),
                    stderr_digest=sha256_digest(stderr),
                    artifacts=artifacts,
                    unexpected_artifacts=unexpected_artifacts,
                    resource_usage=resource_usage,
                    cleanup_complete=False,
                    security_boundary_claimed=True,
                    problem_code="UNEXPECTED_ARTIFACT",
                    problem_message=(
                        "Unexpected artifacts were produced: "
                        + ", ".join(unexpected_artifacts)
                    ),
                )

            # --------------------------------------------------------
            # PASS.
            # --------------------------------------------------------

            completed_at = datetime.now(UTC)

            return SandboxExecutionResultV3(
                run_id=spec.run_id,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                isolation_class=(
                    IsolationClass.PRODUCTION_SECURITY_BOUNDARY
                ),
                outcome=SandboxOutcome.PASS,
                requested_controls=requested,
                enforced_controls=requested,
                missing_controls=frozenset(),
                started_at=started_at,
                completed_at=completed_at,
                exit_code=exit_code,
                timed_out=timed_out,
                stdout=stdout,
                stderr=stderr,
                stdout_digest=sha256_digest(stdout),
                stderr_digest=sha256_digest(stderr),
                artifacts=artifacts,
                unexpected_artifacts=unexpected_artifacts,
                resource_usage=resource_usage,
                cleanup_complete=True,
                security_boundary_claimed=True,
                problem_code=None,
                problem_message=None,
            )

        except FileNotFoundError as exc:
            completed_at = datetime.now(UTC)

            return SandboxExecutionResultV3(
                run_id=spec.run_id,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                isolation_class=(
                    IsolationClass.PRODUCTION_SECURITY_BOUNDARY
                ),
                outcome=SandboxOutcome.ERROR,
                requested_controls=requested,
                enforced_controls=frozenset(),
                missing_controls=requested,
                started_at=started_at,
                completed_at=completed_at,
                exit_code=None,
                timed_out=False,
                stdout=stdout,
                stderr=stderr,
                stdout_digest=sha256_digest(stdout),
                stderr_digest=sha256_digest(stderr),
                artifacts=artifacts,
                unexpected_artifacts=unexpected_artifacts,
                resource_usage=resource_usage,
                cleanup_complete=False,
                security_boundary_claimed=False,
                problem_code="DOCKER_NOT_AVAILABLE",
                problem_message=str(exc),
            )

        except Exception as exc:
            completed_at = datetime.now(UTC)

            return SandboxExecutionResultV3(
                run_id=spec.run_id,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                isolation_class=(
                    IsolationClass.PRODUCTION_SECURITY_BOUNDARY
                ),
                outcome=SandboxOutcome.ERROR,
                requested_controls=requested,
                enforced_controls=requested,
                missing_controls=frozenset(),
                started_at=started_at,
                completed_at=completed_at,
                exit_code=exit_code,
                timed_out=timed_out,
                stdout=stdout,
                stderr=stderr,
                stdout_digest=sha256_digest(stdout),
                stderr_digest=sha256_digest(stderr),
                artifacts=artifacts,
                unexpected_artifacts=unexpected_artifacts,
                resource_usage=resource_usage,
                cleanup_complete=False,
                security_boundary_claimed=False,
                problem_code="SANDBOX_EXECUTION_ERROR",
                problem_message=str(exc),
            )

        finally:
            # --------------------------------------------------------
            # Container cleanup MUST happen after docker cp.
            # --------------------------------------------------------

            self._docker_rm(container_name)

            if run_root is not None:
                shutil.rmtree(
                    run_root,
                    ignore_errors=True,
                )


    # ------------------------------------------------------------------
    # Docker command construction
    # ------------------------------------------------------------------

    def _build_docker_command(
        self,
        *,
        spec: SandboxExecutionSpec,
        container_name: str,
        container_output: Path,
    ) -> list[str]:

        limits = spec.policy.limits

        command: list[str] = [
            self.docker_binary,
            "run",
            *(() if spec.stdin is None else ("--interactive",)),

            # Do NOT use --rm.
            #
            # The container must remain available long enough for
            # docker cp to retrieve /mie/output.
            "--name",
            container_name,

            "--network",
            (
                self.allowlist_network
                if spec.policy.network.mode is NetworkMode.ALLOWLIST
                else "none"
            ),

            "--read-only",

            "--security-opt",
            "no-new-privileges:true",

            "--cap-drop",
            "ALL",

            "--user",
            f"{self.container_uid}:{self.container_gid}",

            "--pids-limit",
            str(limits.process_count),
        ]

        if limits.memory_bytes is not None:
            command.extend(
                [
                    "--memory",
                    str(limits.memory_bytes),
                ]
            )

        if limits.cpu_seconds is not None:
            command.extend(
                [
                    "--cpus",
                    str(max(1, limits.cpu_seconds)),
                ]
            )

        # Dedicated writable areas.
        command.extend(
            [
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,size=64m",

                "--tmpfs",
                "/mie:rw,nosuid,nodev,size=64m,mode=1777",

                # Dedicated host-side output directory.
                # This is the only writable host path exposed to the
                # container and is used solely for declared artifacts.
                "--mount",
                (
                    "type=bind,"
                    f"src={container_output.resolve()},"
                    "dst=/mie/output"
                ),
            ]
        )

        # Explicit environment only.
        command.extend(
            [
                "--env",
                "PYTHONUNBUFFERED=1",

                "--env",
                "PYTHONDONTWRITEBYTECODE=1",
            ]
        )

        for key, value in sorted(
            spec.environment.items()
        ):
            command.extend(
                [
                    "--env",
                    f"{key}={value}",
                ]
            )

        # Explicit host mounts only.
        for mount in spec.mounts:
            source = str(
                Path(mount.source).resolve()
            )

            destination = (
                self._validate_container_relative_path(
                    mount.destination
                )
            )

            mode = (
                "ro"
                if mount.read_only
                else "rw=true"
            )

            command.extend(
                [
                    "--mount",
                    (
                        f"type=bind,"
                        f"src={source},"
                        f"dst={destination},"
                        f"{mode}"
                    ),
                ]
            )

        command.extend(
            [
                self.image,
                *spec.argv,
            ]
        )

        return command

    # ------------------------------------------------------------------
    # Docker output collection
    # ------------------------------------------------------------------

    def _copy_container_output(
        self,
        *,
        container_name: str,
        output_dir: Path,
    ) -> None:
        """
        Copy /mie/output from the live container.

        This MUST occur before docker rm.

        Docker cp accepts a directory path and copies its contents into
        the host destination.
        """

        staging = output_dir / "collected"

        staging.mkdir(
            parents=True,
            exist_ok=True,
        )

        command = [
            self.docker_binary,
            "cp",
            f"{container_name}:/mie/output/.",
            str(staging),
        ]

        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=30,
            check=False,
        )

        if completed.returncode != 0:
            message = (
                completed.stderr.decode(
                    "utf-8",
                    errors="replace",
                ).strip()
            )

            # An empty /mie/output directory is a valid execution state.
            #
            # Docker cp returns an error if the source path has no
            # directory contents in some Docker Desktop configurations.
            #
            # If there are no declared artifacts, this is not an error.
            #
            # If artifacts are declared, the artifact validator will
            # correctly report a missing required artifact.
            if "Could not find the file /mie/output/." in message:
                return

            raise DockerOutputCollectionError(
                "DOCKER_OUTPUT_COLLECTION_ERROR",
                f"failed to collect Docker output: {message}",
            )

    # ------------------------------------------------------------------
    # Artifact handling
    # ------------------------------------------------------------------

    def _collect_artifacts(
        self,
        *,
        spec: SandboxExecutionSpec,
        output_dir: Path,
    ) -> tuple[
        tuple[CollectedArtifactCandidate, ...],
        tuple[str, ...],
    ]:
        """
        Validate the copied /mie/output tree.

        Security rule:

          declared artifacts are allowed;
          everything else is unexpected.

        Missing required artifacts are an artifact error.
        Unexpected artifacts are a separate security failure.
        """

        source = output_dir / "collected"

        if self.collection_root is None:
            staging = source
        else:
            safe_run_id = spec.run_id.replace(":", "_")
            staging = self.collection_root / safe_run_id
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(
                parents=True,
                exist_ok=True,
            )
            if source.exists():
                shutil.copytree(
                    source,
                    staging,
                    dirs_exist_ok=True,
                )

        if not staging.exists():
            staging.mkdir(
                parents=True,
                exist_ok=True,
            )

        declared_paths = {
            declaration.relative_path
            for declaration in spec.artifacts
        }

        actual_files: list[str] = []

        if staging.exists():
            for path in staging.rglob("*"):
                if path.is_file():
                    actual_files.append(
                        path.relative_to(
                            staging
                        ).as_posix()
                    )

        actual_set = set(actual_files)

        unexpected = tuple(
            sorted(
                actual_set - declared_paths
            )
        )

        if unexpected:
            raise UnexpectedArtifactError(
                unexpected
            )

        candidates: list[
            CollectedArtifactCandidate
        ] = []

        for declaration in spec.artifacts:
            path = (
                staging
                / declaration.relative_path
            )

            if not path.exists():
                if declaration.required:
                    raise ArtifactCollectionError(
                        "SANDBOX_ARTIFACT_ERROR",
                        (
                            "required artifact missing: "
                            f"{declaration.relative_path}"
                        ),
                    )

                continue

            if not path.is_file():
                raise ArtifactCollectionError(
                    "SANDBOX_ARTIFACT_ERROR",
                    (
                        "declared artifact is not a file: "
                        f"{declaration.relative_path}"
                    ),
                )

            size = path.stat().st_size

            if size > declaration.max_bytes:
                raise ArtifactCollectionError(
                    "SANDBOX_ARTIFACT_ERROR",
                    (
                        "artifact exceeds maximum size: "
                        f"{declaration.relative_path}"
                    ),
                )

            digest = sha256_digest(
                path.read_bytes()
            )

            if (
                declaration.expected_digest
                is not None
                and digest
                != declaration.expected_digest
            ):
                raise ArtifactCollectionError(
                    "SANDBOX_ARTIFACT_ERROR",
                    (
                        "artifact digest mismatch: "
                        f"{declaration.relative_path}"
                    ),
                )

            candidates.append(
                CollectedArtifactCandidate(
                    artifact_id=declaration.artifact_id,
                    relative_path=declaration.relative_path,
                    media_type=declaration.media_type,
                    size_bytes=size,
                    reported_digest=digest,
                    collection_root=str(staging),
                    run_id=spec.run_id,
                )
            )

        return (
            tuple(candidates),
            unexpected,
        )

    # ------------------------------------------------------------------
    # Blocked result
    # ------------------------------------------------------------------

    def _blocked_result(
        self,
        *,
        spec: SandboxExecutionSpec,
        started_at: datetime,
        requested: frozenset[SandboxControl],
        problem_code: str,
        problem_message: str,
    ) -> SandboxExecutionResultV3:

        completed_at = datetime.now(
            UTC
        )

        return SandboxExecutionResultV3(
            run_id=spec.run_id,
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            isolation_class=(
                IsolationClass.PRODUCTION_SECURITY_BOUNDARY
            ),
            outcome=SandboxOutcome.BLOCKED,
            requested_controls=requested,
            enforced_controls=frozenset(),
            missing_controls=requested,
            started_at=started_at,
            completed_at=completed_at,
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
            problem_code=problem_code,
            problem_message=problem_message,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_run_id(
        run_id: str,
    ) -> str:

        value = "".join(
            character
            if character.isalnum()
            or character in "-_"
            else "-"
            for character in run_id
        )

        value = value.strip("-")

        if not value:
            value = "run"

        return value[:48]

    @staticmethod
    def _bound_output(
        value: bytes | None,
        limit: int | None,
    ) -> bytes:

        if value is None:
            return b""

        data = bytes(value)

        if limit is None:
            return data

        if limit < 0:
            return data

        return data[:limit]

    def _docker_stop(
        self,
        container_name: str,
    ) -> None:

        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                [
                    self.docker_binary,
                    "stop",
                    "--time",
                    "1",
                    container_name,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )

    def _docker_rm(
        self,
        container_name: str,
    ) -> None:

        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                [
                    self.docker_binary,
                    "rm",
                    "-f",
                    container_name,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )

    @staticmethod
    def _validate_container_relative_path(
        value: str,
    ) -> str:

        path = PurePosixPath(value)

        if path.is_absolute():
            raise ValueError(

                    "container mount destination "
                    f"must be relative: {value}"

            )

        if ".." in path.parts:
            raise ValueError(

                    "container mount destination "
                    f"traversal: {value}"

            )

        return "/" + path.as_posix()


class ArtifactCollectionError(
    RuntimeError
):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


class UnexpectedArtifactError(
    RuntimeError
):
    def __init__(
        self,
        paths: tuple[str, ...],
    ) -> None:
        super().__init__(
            "unexpected artifacts: "
            + ", ".join(paths)
        )
        self.paths = paths


class DockerOutputCollectionError(
    RuntimeError
):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code










