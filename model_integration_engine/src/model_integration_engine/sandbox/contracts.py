"""Production-oriented sandbox contracts.

These contracts describe required controls and actual enforcement separately.
A backend must never label itself a security boundary merely because it starts a
subprocess.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Protocol

from ..domain import JSONValue


class SandboxControl(StrEnum):
    CONTROLLED_EXECUTION = "controlled_execution"
    FILESYSTEM_ISOLATION = "filesystem_isolation"
    NETWORK_POLICY = "network_policy"
    PROCESS_LIMITS = "process_limits"
    PERMISSION_BOUNDARY = "permission_boundary"
    ARTIFACT_ALLOWLIST = "artifact_allowlist"
    ARTIFACT_DIGESTING = "artifact_digesting"
    RESULT_CAPTURE = "result_capture"
    FAILURE_ISOLATION = "failure_isolation"
    CLEAN_ENVIRONMENT = "clean_environment"
    CLEANUP = "cleanup"
    TIMEOUT = "timeout"


class NetworkMode(StrEnum):
    DENY = "DENY"
    ALLOWLIST = "ALLOWLIST"
    INHERIT = "INHERIT"


class CodeTrust(StrEnum):
    TRUSTED_ENGINE_HARNESS = "TRUSTED_ENGINE_HARNESS"
    REVIEWED_ADAPTER = "REVIEWED_ADAPTER"
    UNTRUSTED_GENERATED = "UNTRUSTED_GENERATED"


class SandboxOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


class IsolationClass(StrEnum):
    PRODUCTION_SECURITY_BOUNDARY = "PRODUCTION_SECURITY_BOUNDARY"
    REFERENCE_NOT_SECURITY_BOUNDARY = "REFERENCE_NOT_SECURITY_BOUNDARY"
    TEST_DOUBLE = "TEST_DOUBLE"


@dataclass(frozen=True, slots=True)
class ProcessLimits:
    timeout_seconds: float
    cpu_seconds: int | None = None
    memory_bytes: int | None = None
    output_bytes: int = 4 * 1024 * 1024
    file_bytes: int = 64 * 1024 * 1024
    process_count: int = 16

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.output_bytes <= 0 or self.file_bytes <= 0 or self.process_count <= 0:
            raise ValueError("resource limits must be positive")


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    mode: NetworkMode
    allowed_endpoints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode is NetworkMode.ALLOWLIST and not self.allowed_endpoints:
            raise ValueError("ALLOWLIST network policy requires endpoints")
        if self.mode is NetworkMode.DENY and self.allowed_endpoints:
            raise ValueError("DENY network policy cannot include endpoints")


@dataclass(frozen=True, slots=True)
class SandboxMount:
    source: str
    destination: str
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class ArtifactDeclaration:
    artifact_id: str
    relative_path: str
    media_type: str
    required: bool = True
    expected_digest: str | None = None
    max_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("artifact path must be relative and traversal-free")
        if not self.artifact_id or not self.media_type or self.max_bytes <= 0:
            raise ValueError("artifact declaration is incomplete")


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    policy_id: str
    policy_version: str
    required_controls: frozenset[SandboxControl]
    network: NetworkPolicy
    limits: ProcessLimits
    filesystem_isolation_required: bool = True
    non_root_required: bool = True
    allowed_permissions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SandboxExecutionSpec:
    run_id: str
    argv: tuple[str, ...]
    environment: Mapping[str, str]
    mounts: tuple[SandboxMount, ...]
    output_directory: str
    artifacts: tuple[ArtifactDeclaration, ...]
    policy: SandboxPolicy
    code_trust: CodeTrust
    stdin: bytes | None = None
    working_directory: str = "."

    def __post_init__(self) -> None:
        if not self.run_id or not self.argv:
            raise ValueError("sandbox run_id and argv are required")
        output = PurePosixPath(self.output_directory)
        work = PurePosixPath(self.working_directory)
        for value in (output, work):
            if value.is_absolute() or ".." in value.parts:
                raise ValueError("sandbox paths must be relative and traversal-free")


@dataclass(frozen=True, slots=True)
class SandboxCapabilitiesV3:
    backend_id: str
    backend_version: str
    isolation_class: IsolationClass
    enforceable_controls: frozenset[SandboxControl]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CollectedArtifactCandidate:
    artifact_id: str
    relative_path: str
    media_type: str
    size_bytes: int
    reported_digest: str
    collection_root: str
    run_id: str


@dataclass(frozen=True, slots=True)
class SandboxExecutionResultV3:
    run_id: str
    backend_id: str
    backend_version: str
    isolation_class: IsolationClass
    outcome: SandboxOutcome
    requested_controls: frozenset[SandboxControl]
    enforced_controls: frozenset[SandboxControl]
    missing_controls: frozenset[SandboxControl]
    started_at: datetime
    completed_at: datetime
    exit_code: int | None
    timed_out: bool
    stdout: bytes
    stderr: bytes
    stdout_digest: str
    stderr_digest: str
    artifacts: tuple[CollectedArtifactCandidate, ...]
    unexpected_artifacts: tuple[str, ...]
    resource_usage: Mapping[str, JSONValue]
    cleanup_complete: bool
    security_boundary_claimed: bool
    problem_code: str | None = None
    problem_message: str | None = None


class ProductionSandboxBackend(Protocol):
    def capabilities(self) -> SandboxCapabilitiesV3: ...

    def execute(self, spec: SandboxExecutionSpec) -> SandboxExecutionResultV3: ...
