"""Clearly marked reference subprocess backend.

This backend demonstrates execution lifecycle, limits, capture, artifact
collection, and cleanup. It is NOT a filesystem/network security sandbox and
refuses untrusted generated code or policies requiring controls it cannot
actually enforce.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..evidence import sha256_digest
from .contracts import (
    CodeTrust,
    CollectedArtifactCandidate,
    IsolationClass,
    SandboxCapabilitiesV3,
    SandboxControl,
    SandboxExecutionResultV3,
    SandboxExecutionSpec,
    SandboxOutcome,
)


@dataclass(slots=True)
class ReferenceSubprocessSandbox:
    root: Path
    collection_root: Path
    backend_id: str = "mie.sandbox.reference-subprocess"
    backend_version: str = "0.3.0"

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.collection_root = self.collection_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.collection_root.mkdir(parents=True, exist_ok=True)

    def capabilities(self) -> SandboxCapabilitiesV3:
        controls = {
            SandboxControl.CONTROLLED_EXECUTION,
            SandboxControl.PROCESS_LIMITS,
            SandboxControl.ARTIFACT_ALLOWLIST,
            SandboxControl.ARTIFACT_DIGESTING,
            SandboxControl.RESULT_CAPTURE,
            SandboxControl.FAILURE_ISOLATION,
            SandboxControl.CLEAN_ENVIRONMENT,
            SandboxControl.CLEANUP,
            SandboxControl.TIMEOUT,
        }
        return SandboxCapabilitiesV3(
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            isolation_class=IsolationClass.REFERENCE_NOT_SECURITY_BOUNDARY,
            enforceable_controls=frozenset(controls),
            notes=(
                "No kernel-enforced filesystem isolation.",
                "No enforceable network policy.",
                "Never use for untrusted generated adapters.",
            ),
        )

    def execute(self, spec: SandboxExecutionSpec) -> SandboxExecutionResultV3:
        started = datetime.now(UTC)
        capabilities = self.capabilities()
        missing = spec.policy.required_controls - capabilities.enforceable_controls
        unsafe_untrusted = spec.code_trust is CodeTrust.UNTRUSTED_GENERATED
        if missing or unsafe_untrusted:
            code = (
                "REFERENCE_BACKEND_UNSAFE_FOR_UNTRUSTED"
                if unsafe_untrusted
                else "SANDBOX_CONTROL_UNAVAILABLE"
            )
            return self._blocked(spec, started, capabilities, missing, code)

        run_directory = Path(
            tempfile.mkdtemp(prefix=f"{_safe_name(spec.run_id)}-", dir=self.root)
        )
        work = run_directory / spec.working_directory
        outputs = run_directory / spec.output_directory
        work.mkdir(parents=True, exist_ok=True)
        outputs.mkdir(parents=True, exist_ok=True)
        collection = self.collection_root / _safe_name(spec.run_id)
        if collection.exists():
            shutil.rmtree(collection)
        collection.mkdir(parents=True)

        for mount in spec.mounts:
            source = Path(mount.source).resolve()
            destination = (run_directory / mount.destination).resolve()
            destination.relative_to(run_directory)
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            if mount.read_only:
                for path in [destination, *destination.rglob("*")] if destination.is_dir() else [destination]:
                    try:
                        path.chmod(0o500 if path.is_dir() else 0o400)
                    except OSError:
                        pass

        environment = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "HOME": str(run_directory / "home"),
            "TMPDIR": str(run_directory / "tmp"),
            **dict(spec.environment),
        }
        Path(environment["HOME"]).mkdir()
        Path(environment["TMPDIR"]).mkdir()
        preexec = _limit_process(spec) if os.name == "posix" else None
        process = None
        stdout = b""
        stderr = b""
        timed_out = False
        exit_code = None
        problem_code = None
        problem_message = None
        outcome = SandboxOutcome.ERROR
        artifacts: list[CollectedArtifactCandidate] = []
        unexpected: tuple[str, ...] = ()
        cleanup_complete = False
        monotonic_start = time.monotonic()
        try:
            process = subprocess.Popen(
                spec.argv,
                cwd=work,
                env=environment,
                stdin=subprocess.PIPE if spec.stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=os.name != "posix",
                preexec_fn=preexec,
            )
            try:
                stdout, stderr = process.communicate(
                    input=spec.stdin, timeout=spec.policy.limits.timeout_seconds
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                stdout, stderr = process.communicate()
            exit_code = process.returncode
            limit = spec.policy.limits.output_bytes
            stdout = stdout[:limit]
            stderr = stderr[:limit]
            if timed_out:
                outcome = SandboxOutcome.TIMEOUT
                problem_code = "SANDBOX_TIMEOUT"
            elif exit_code != 0:
                outcome = SandboxOutcome.FAIL
                problem_code = "SANDBOX_PROCESS_FAILED"
            else:
                artifacts, unexpected = self._collect(spec, run_directory, collection)
                if unexpected:
                    outcome = SandboxOutcome.FAIL
                    problem_code = "UNEXPECTED_ARTIFACT"
                    problem_message = ", ".join(unexpected)
                else:
                    outcome = SandboxOutcome.PASS
        except Exception as exc:
            outcome = SandboxOutcome.ERROR
            problem_code = "SANDBOX_EXECUTION_ERROR"
            problem_message = str(exc)[:500]
        finally:
            try:
                shutil.rmtree(run_directory)
                cleanup_complete = not run_directory.exists()
            except OSError:
                cleanup_complete = False

        completed = datetime.now(UTC)
        return SandboxExecutionResultV3(
            run_id=spec.run_id,
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            isolation_class=IsolationClass.REFERENCE_NOT_SECURITY_BOUNDARY,
            outcome=outcome,
            requested_controls=spec.policy.required_controls,
            enforced_controls=capabilities.enforceable_controls
            & spec.policy.required_controls,
            missing_controls=frozenset(),
            started_at=started,
            completed_at=completed,
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
            stdout_digest=sha256_digest(stdout),
            stderr_digest=sha256_digest(stderr),
            artifacts=tuple(artifacts),
            unexpected_artifacts=unexpected,
            resource_usage={
                "wall_seconds": max(0.0, time.monotonic() - monotonic_start),
                "stdout_bytes_retained": len(stdout),
                "stderr_bytes_retained": len(stderr),
            },
            cleanup_complete=cleanup_complete,
            security_boundary_claimed=False,
            problem_code=problem_code,
            problem_message=problem_message,
        )

    def _collect(self, spec, run_directory, collection):
        output_root = (run_directory / spec.output_directory).resolve()
        declarations = {item.relative_path: item for item in spec.artifacts}
        actual = {
            path.relative_to(output_root).as_posix(): path
            for path in output_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        unexpected = tuple(sorted(set(actual) - set(declarations)))
        artifacts = []
        for relative, declaration in sorted(declarations.items()):
            source = actual.get(relative)
            if source is None:
                continue
            size = source.stat().st_size
            if size > declaration.max_bytes:
                raise ValueError(f"artifact exceeds declaration limit: {relative}")
            destination = collection / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            digest = _hash_file(destination)
            artifacts.append(
                CollectedArtifactCandidate(
                    artifact_id=declaration.artifact_id,
                    relative_path=relative,
                    media_type=declaration.media_type,
                    size_bytes=size,
                    reported_digest=digest,
                    collection_root=str(collection),
                    run_id=spec.run_id,
                )
            )
        missing = [
            item.relative_path
            for item in spec.artifacts
            if item.required and item.relative_path not in actual
        ]
        if missing:
            raise ValueError("required artifact missing: " + ", ".join(missing))
        return artifacts, unexpected

    def _blocked(self, spec, started, capabilities, missing, code):
        now = datetime.now(UTC)
        return SandboxExecutionResultV3(
            run_id=spec.run_id,
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            isolation_class=IsolationClass.REFERENCE_NOT_SECURITY_BOUNDARY,
            outcome=SandboxOutcome.BLOCKED,
            requested_controls=spec.policy.required_controls,
            enforced_controls=frozenset(),
            missing_controls=frozenset(missing),
            started_at=started,
            completed_at=now,
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
            problem_code=code,
            problem_message=(
                "Reference backend cannot run untrusted generated code."
                if code == "REFERENCE_BACKEND_UNSAFE_FOR_UNTRUSTED"
                else "Missing mandatory controls: "
                + ", ".join(sorted(item.value for item in missing))
            ),
        )


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)[:80]


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _limit_process(spec):
    def apply_limits() -> None:
        import resource

        os.setsid()
        limits = spec.policy.limits
        if limits.cpu_seconds is not None:
            resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        if limits.memory_bytes is not None:
            resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.file_bytes, limits.file_bytes))

    return apply_limits
