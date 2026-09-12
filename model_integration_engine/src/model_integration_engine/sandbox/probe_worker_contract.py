"""Serialized input contract for the sandboxed behavioral-probe worker."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from ..application.probes import ProbeCase, ProbeKind, ProbePlan
from ..contracts import ResourceLimits
from ..domain import JSONValue, SubjectKind, SubjectRef
from ..evidence import sha256_digest

WORKER_SPEC_SCHEMA_VERSION = "0.1.0"


def _subject_to_document(subject: SubjectRef) -> dict[str, JSONValue]:
    return {
        "kind": subject.kind.value,
        "subject_id": subject.subject_id,
        "version": subject.version,
        "digest": subject.digest,
    }


def _subject_from_document(value: object) -> SubjectRef:
    if not isinstance(value, Mapping):
        raise ValueError("subject must be an object")
    required = {"kind", "subject_id", "version", "digest"}
    if set(value) != required:
        raise ValueError("subject contains unexpected fields")
    kind = value.get("kind")
    subject_id = value.get("subject_id")
    version = value.get("version")
    digest = value.get("digest")
    if not isinstance(kind, str) or not isinstance(subject_id, str):
        raise ValueError("subject kind and subject_id must be strings")
    if version is not None and not isinstance(version, str):
        raise ValueError("subject version must be a string or null")
    if digest is not None and not isinstance(digest, str):
        raise ValueError("subject digest must be a string or null")
    return SubjectRef(
        kind=SubjectKind(kind),
        subject_id=subject_id,
        version=version,
        digest=digest,
    )


def _probe_case_to_document(case: ProbeCase) -> dict[str, JSONValue]:
    return {
        "probe_id": case.probe_id,
        "kind": case.kind.value,
        "capability_key": case.capability_key,
        "subject": _subject_to_document(case.subject),
        "fixture_digest": case.fixture_digest,
    }


def _probe_case_from_document(value: object) -> ProbeCase:
    if not isinstance(value, Mapping):
        raise ValueError("probe case must be an object")
    required = {
        "probe_id",
        "kind",
        "capability_key",
        "subject",
        "fixture_digest",
    }
    if set(value) != required:
        raise ValueError("probe case contains unexpected fields")
    probe_id = value.get("probe_id")
    kind = value.get("kind")
    capability_key = value.get("capability_key")
    fixture_digest = value.get("fixture_digest")
    if not all(isinstance(item, str) for item in (probe_id, kind, capability_key, fixture_digest)):
        raise ValueError("probe case string fields are invalid")
    return ProbeCase(
        probe_id=probe_id,
        kind=ProbeKind(kind),
        capability_key=capability_key,
        subject=_subject_from_document(value.get("subject")),
        fixture_digest=fixture_digest,
    )


def _probe_plan_to_document(plan: ProbePlan) -> dict[str, JSONValue]:
    return {
        "plan_id": plan.plan_id,
        "suite_id": plan.suite_id,
        "suite_version": plan.suite_version,
        "deployment": _subject_to_document(plan.deployment),
        "runtime": _subject_to_document(plan.runtime),
        "adapter_id": plan.adapter_id,
        "configuration_digest": plan.configuration_digest,
        "environment_id": plan.environment_id,
        "cases": [_probe_case_to_document(case) for case in plan.cases],
        "required_controls": list(plan.required_controls),
    }


def _probe_plan_from_document(value: object) -> ProbePlan:
    if not isinstance(value, Mapping):
        raise ValueError("probe plan must be an object")
    required = {
        "plan_id",
        "suite_id",
        "suite_version",
        "deployment",
        "runtime",
        "adapter_id",
        "configuration_digest",
        "environment_id",
        "cases",
        "required_controls",
    }
    if set(value) != required:
        raise ValueError("probe plan contains unexpected fields")
    string_fields = (
        "plan_id",
        "suite_id",
        "suite_version",
        "adapter_id",
        "configuration_digest",
        "environment_id",
    )
    for field_name in string_fields:
        if not isinstance(value.get(field_name), str):
            raise ValueError(f"probe plan field {field_name} must be a string")
    cases_raw = value.get("cases")
    controls_raw = value.get("required_controls")
    if not isinstance(cases_raw, list) or not all(isinstance(item, Mapping) for item in cases_raw):
        raise ValueError("probe plan cases must be an array of objects")
    if not isinstance(controls_raw, list) or not all(isinstance(item, str) for item in controls_raw):
        raise ValueError("probe plan required_controls must be an array of strings")
    return ProbePlan(
        plan_id=value["plan_id"],
        suite_id=value["suite_id"],
        suite_version=value["suite_version"],
        deployment=_subject_from_document(value.get("deployment")),
        runtime=_subject_from_document(value.get("runtime")),
        adapter_id=value["adapter_id"],
        configuration_digest=value["configuration_digest"],
        environment_id=value["environment_id"],
        cases=tuple(_probe_case_from_document(item) for item in cases_raw),
        required_controls=tuple(controls_raw),
    )


def _limits_to_document(limits: ResourceLimits) -> dict[str, JSONValue]:
    return {
        "timeout_seconds": float(limits.timeout_seconds),
        "max_entries": limits.max_entries,
        "max_metadata_bytes": limits.max_metadata_bytes,
        "max_output_bytes": limits.max_output_bytes,
        "max_processes": limits.max_processes,
        "max_memory_bytes": limits.max_memory_bytes,
        "max_disk_bytes": limits.max_disk_bytes,
    }


def _limits_from_document(value: object) -> ResourceLimits:
    if not isinstance(value, Mapping):
        raise ValueError("limits must be an object")
    required = {
        "timeout_seconds",
        "max_entries",
        "max_metadata_bytes",
        "max_output_bytes",
        "max_processes",
        "max_memory_bytes",
        "max_disk_bytes",
    }
    if set(value) != required:
        raise ValueError("limits contain unexpected fields")
    return ResourceLimits(
        timeout_seconds=float(value["timeout_seconds"]),
        max_entries=int(value["max_entries"]),
        max_metadata_bytes=int(value["max_metadata_bytes"]),
        max_output_bytes=int(value["max_output_bytes"]),
        max_processes=int(value["max_processes"]),
        max_memory_bytes=None if value["max_memory_bytes"] is None else int(value["max_memory_bytes"]),
        max_disk_bytes=None if value["max_disk_bytes"] is None else int(value["max_disk_bytes"]),
    )


@dataclass(frozen=True, slots=True)
class ProbeWorkerContextSpec:
    run_id: str
    correlation_id: str
    deadline: datetime
    policy_id: str
    policy_version: str
    workspace_id: str
    allowed_permissions: tuple[str, ...]
    limits: ResourceLimits

    def to_document(self) -> dict[str, JSONValue]:
        return {
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "deadline": self.deadline.isoformat(),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "workspace_id": self.workspace_id,
            "allowed_permissions": list(self.allowed_permissions),
            "limits": _limits_to_document(self.limits),
        }

    @classmethod
    def from_document(cls, value: object) -> ProbeWorkerContextSpec:
        if not isinstance(value, Mapping):
            raise ValueError("worker context must be an object")
        required = {
            "run_id",
            "correlation_id",
            "deadline",
            "policy_id",
            "policy_version",
            "workspace_id",
            "allowed_permissions",
            "limits",
        }
        if set(value) != required:
            raise ValueError("worker context contains unexpected fields")
        permissions = value.get("allowed_permissions")
        if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
            raise ValueError("allowed_permissions must be an array of strings")
        strings = ("run_id", "correlation_id", "policy_id", "policy_version", "workspace_id", "deadline")
        if not all(isinstance(value.get(name), str) for name in strings):
            raise ValueError("worker context string fields are invalid")
        return cls(
            run_id=value["run_id"],
            correlation_id=value["correlation_id"],
            deadline=datetime.fromisoformat(value["deadline"]),
            policy_id=value["policy_id"],
            policy_version=value["policy_version"],
            workspace_id=value["workspace_id"],
            allowed_permissions=tuple(permissions),
            limits=_limits_from_document(value.get("limits")),
        )


@dataclass(frozen=True, slots=True)
class ProbeWorkerSpec:
    schema_version: str
    run_id: str
    runtime_locator: str
    adapter_id: str
    adapter_configuration: Mapping[str, JSONValue]
    plan: ProbePlan
    context: ProbeWorkerContextSpec
    output_artifact_path: str

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        runtime_locator: str,
        adapter_id: str,
        adapter_configuration: Mapping[str, JSONValue],
        plan: ProbePlan,
        context: ProbeWorkerContextSpec,
        output_artifact_path: str,
    ) -> ProbeWorkerSpec:
        if not run_id.strip():
            raise ValueError("run_id must be non-empty")
        if not runtime_locator.strip():
            raise ValueError("runtime_locator must be non-empty")
        if not adapter_id.strip():
            raise ValueError("adapter_id must be non-empty")
        if not output_artifact_path.strip():
            raise ValueError("output_artifact_path must be non-empty")
        if context.run_id != run_id:
            raise ValueError("worker context run_id must match run_id")
        if plan.adapter_id != adapter_id:
            raise ValueError("plan adapter_id must match adapter_id")
        if plan.configuration_digest != str(adapter_configuration.get("configuration_digest", "")):
            raise ValueError("adapter configuration digest must match the probe plan")
        return cls(
            schema_version=WORKER_SPEC_SCHEMA_VERSION,
            run_id=run_id,
            runtime_locator=runtime_locator,
            adapter_id=adapter_id,
            adapter_configuration=dict(adapter_configuration),
            plan=plan,
            context=context,
            output_artifact_path=output_artifact_path,
        )

    def to_document(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "runtime_locator": self.runtime_locator,
            "adapter_id": self.adapter_id,
            "adapter_configuration": dict(self.adapter_configuration),
            "plan": _probe_plan_to_document(self.plan),
            "context": self.context.to_document(),
            "output_artifact_path": self.output_artifact_path,
        }

    @property
    def digest(self) -> str:
        return sha256_digest(self.to_document())

    @classmethod
    def from_document(cls, value: object) -> ProbeWorkerSpec:
        if not isinstance(value, Mapping):
            raise ValueError("worker spec must be an object")
        required = {
            "schema_version",
            "run_id",
            "runtime_locator",
            "adapter_id",
            "adapter_configuration",
            "plan",
            "context",
            "output_artifact_path",
        }
        if set(value) != required:
            raise ValueError("worker spec contains unexpected fields")
        if value.get("schema_version") != WORKER_SPEC_SCHEMA_VERSION:
            raise ValueError("unsupported probe worker schema version")
        adapter_configuration = value.get("adapter_configuration")
        if not isinstance(adapter_configuration, Mapping):
            raise ValueError("adapter_configuration must be an object")
        return cls.create(
            run_id=value["run_id"],
            runtime_locator=value["runtime_locator"],
            adapter_id=value["adapter_id"],
            adapter_configuration=dict(adapter_configuration),
            plan=_probe_plan_from_document(value.get("plan")),
            context=ProbeWorkerContextSpec.from_document(value.get("context")),
            output_artifact_path=value["output_artifact_path"],
        )
