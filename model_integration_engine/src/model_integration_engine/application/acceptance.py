"""Generic real-deployment acceptance orchestration and report generation.

The runner reuses the established Ollama, evidence, probe, compatibility,
identity, and package components.  It never substitutes fixture evidence for a
live endpoint, never requests approval, and never writes a capability registry.
"""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..contracts import OperationContext, ResourceLimits
from ..domain import EvidenceRecord, JSONValue, TestOutcome
from ..evidence import deterministic_id, sha256_digest, utc_now
from ..inspectors.gguf import GGUFInspectionResult, GGUFInspector
from ..inspectors.template import ChatTemplateInspection, GenericChatTemplateInspector
from ..inspectors.tokenizer import GenericTokenizerInspector, TokenizerInspection
from ..packaging.draft import DraftIntegrationPackageBuilder
from ..plugins.ollama.client import JsonTransport, StdlibJsonTransport
from .lifecycle import Part3LifecycleConfig, Part3LifecycleEngine, Part3LifecycleResult
from .probes import BlockedProbeExecutionBackend
from .vertical_slice import (
    Phase2VerticalSliceEngine,
    VerticalSliceConfig,
    default_target_profile,
    environment_info,
)


@dataclass(frozen=True, slots=True)
class AcceptanceConfig:
    endpoint: str
    model_reference: str
    output_directory: Path
    artifact_path: Path | None = None
    artifact_digest: str | None = None
    registry_snapshot: Mapping[str, Any] | None = None
    user_evidence_document: Mapping[str, JSONValue] | None = None
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.endpoint.strip() or not self.model_reference.strip():
            raise ValueError("endpoint and model_reference are required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.artifact_digest is not None and self.artifact_path is None:
            raise ValueError("artifact_digest requires artifact_path")
        if self.artifact_digest is not None:
            _validate_digest(self.artifact_digest)


@dataclass(frozen=True, slots=True)
class ArtifactInspectionBundle:
    gguf: GGUFInspectionResult
    tokenizer: TokenizerInspection
    template: ChatTemplateInspection

    @property
    def evidence(self) -> tuple[EvidenceRecord, ...]:
        return self.gguf.evidence + self.tokenizer.evidence + self.template.evidence


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    state: str
    output_directory: str
    package_path: str | None
    package_digest: str | None
    approval_requested: bool
    lifecycle: Part3LifecycleResult


@dataclass(slots=True)
class GenericAcceptanceRunner:
    """Run generic acceptance while failing closed at the probe boundary."""

    transport: JsonTransport | None = None
    clock: callable = utc_now

    async def run(self, config: AcceptanceConfig) -> AcceptanceResult:
        output = config.output_directory.resolve()
        output.mkdir(parents=True, exist_ok=True)
        artifact_bundle = self._inspect_artifact(config)
        additional_evidence = artifact_bundle.evidence if artifact_bundle else ()

        environment_material = {
            "endpoint": config.endpoint,
            "platform": platform.platform(),
            "machine": platform.machine() or "unknown",
            "acceptance_mode": "LIVE_ENDPOINT_METADATA_WITH_BLOCKED_BEHAVIORAL_PROBES",
        }
        environment_id = deterministic_id(
            "environment:acceptance", environment_material
        )
        environment = environment_info(
            environment_id=environment_id,
            locality=_endpoint_locality(config.endpoint),
            sandbox_backend_id="mie.probes.blocked-production-unavailable",
            attributes={
                "acceptance_mode": environment_material["acceptance_mode"],
                "production_sandbox_available": False,
                "behavioral_probe_policy": "BLOCKED_PRODUCTION_SANDBOX_UNAVAILABLE",
            },
        )
        transport = self.transport or StdlibJsonTransport()
        blocked_backend = BlockedProbeExecutionBackend(clock=self.clock)
        phase2 = Phase2VerticalSliceEngine(
            transport=transport,
            probe_backend=blocked_backend,
            package_builder=DraftIntegrationPackageBuilder(),
            clock=self.clock,
            engine_version="0.3.0a0",
        )
        vertical_config = VerticalSliceConfig(
            endpoint=config.endpoint,
            model_reference=config.model_reference,
            target_profile=default_target_profile(),
            environment=environment,
            live_validation=True,
            timeout_seconds=config.timeout_seconds,
            include_operational_probes=True,
            user_evidence_document=config.user_evidence_document,
            additional_evidence=additional_evidence,
            registry_snapshot=config.registry_snapshot,
        )
        context = _operation_context(config, environment_id, self.clock)
        lifecycle = await Part3LifecycleEngine(
            phase2=phase2, clock=self.clock
        ).run(
            Part3LifecycleConfig(
                vertical_slice=vertical_config,
                package_store_root=output / "immutable-packages",
                identity_ledger_path=output / "identity-ledger.json",
                artifact_resolution=None,
                request_approval=False,
            ),
            context,
        )

        if lifecycle.submitted_package is None or lifecycle.proposed_package is None:
            self._write_failed_outputs(config, lifecycle, artifact_bundle)
            _write_manifest(output)
            return AcceptanceResult(
                state=lifecycle.state,
                output_directory=str(output),
                package_path=None,
                package_digest=None,
                approval_requested=False,
                lifecycle=lifecycle,
            )

        if lifecycle.approval_request is not None:
            raise RuntimeError("acceptance must not create an approval request")
        proposed = lifecycle.proposed_package.document
        base = proposed["base_package"]
        if base["approval"]["state"] != "NOT_REQUESTED":
            raise RuntimeError("acceptance package approval state must remain NOT_REQUESTED")
        if proposed["lifecycle_state"] != "DRAFT_PENDING_APPROVAL":
            raise RuntimeError("acceptance package left the required draft state")

        package_path = output / "real-draft-integration-package.json"
        _write_json(package_path, proposed)
        self._write_success_outputs(config, lifecycle, artifact_bundle)
        _write_manifest(output)
        return AcceptanceResult(
            state="DRAFT_PENDING_APPROVAL",
            output_directory=str(output),
            package_path=str(package_path),
            package_digest=lifecycle.submitted_package.package_digest,
            approval_requested=False,
            lifecycle=lifecycle,
        )

    def _inspect_artifact(
        self, config: AcceptanceConfig
    ) -> ArtifactInspectionBundle | None:
        if config.artifact_path is None:
            return None
        path = config.artifact_path.resolve()
        gguf = GGUFInspector(clock=self.clock).inspect(
            path, expected_digest=config.artifact_digest
        )
        tokenizer = GenericTokenizerInspector(clock=self.clock).inspect(
            artifact=gguf.artifact,
            metadata=gguf.observed.metadata,
            source_uri=path.as_uri(),
            source_digest=gguf.observed.file_digest,
        )
        template = GenericChatTemplateInspector(clock=self.clock).inspect(
            artifact=gguf.artifact,
            metadata=gguf.observed.metadata,
            source_uri=path.as_uri(),
            source_digest=gguf.observed.file_digest,
        )
        return ArtifactInspectionBundle(gguf, tokenizer, template)

    def _write_success_outputs(
        self,
        config: AcceptanceConfig,
        lifecycle: Part3LifecycleResult,
        artifact: ArtifactInspectionBundle | None,
    ) -> None:
        output = config.output_directory.resolve()
        proposed = lifecycle.proposed_package.document
        base = proposed["base_package"]
        evidence = base["evidence"]
        user_evidence = [item for item in evidence if item["kind"] == "USER_INPUT"]
        live_evidence = [
            item
            for item in evidence
            if item["collector_id"]
            in {
                "mie.discovery.ollama-api",
                "mie.inspector.ollama-model-details",
                "mie.inspector.tokenizer-metadata",
                "mie.inspector.chat-template",
            }
            and item["source"]["uri"].startswith(config.endpoint.rstrip("/"))
            and item["kind"] != "USER_INPUT"
        ]
        _write_json(
            output / "user-supplied-evidence.json",
            {
                "classification": "USER-SUPPLIED EVIDENCE",
                "count": len(user_evidence),
                "evidence": user_evidence,
                "behaviorally_validated": False,
            },
        )
        _write_json(
            output / "live-runtime-evidence.json",
            {
                "classification": "LIVE RUNTIME EVIDENCE",
                "endpoint": base["runtime"]["endpoint"],
                "runtime": base["runtime"],
                "count": len(live_evidence),
                "evidence": live_evidence,
            },
        )
        _write_json(
            output / "identity-reconciliation.json",
            _identity_document(lifecycle, artifact),
        )
        _write_json(
            output / "artifact-evidence.json",
            _artifact_document(artifact, base["runtime"].get("model_digest")),
        )
        _write_json(
            output / "behavioral-probe-evidence.json",
            _probe_document(lifecycle),
        )
        _write_json(
            output / "capability-assessment.json",
            _capability_document(base["capabilities"]),
        )
        _write_json(
            output / "compatibility-assessment.json",
            {
                "classification": "COMPATIBILITY ASSESSMENT",
                **base["compatibility"],
            },
        )
        delta = lifecycle.vertical_slice.capability_delta
        _write_json(
            output / "capability-delta.json",
            delta.as_dict()
            if delta is not None
            else {
                "status": "UNKNOWN_NOT_COMPUTED",
                "read_only": True,
            },
        )
        _write_json(
            output / "run-status.json",
            {
                "state": lifecycle.state,
                "approval_state": base["approval"]["state"],
                "approval_request_created": False,
                "package_digest": lifecycle.submitted_package.package_digest,
                "security_verdict": proposed["security_assessment"]["verdict"],
                "behavioral_probes": "BLOCKED_PRODUCTION_SANDBOX_UNAVAILABLE",
                "sage_accessed": False,
                "registry_modified": False,
            },
        )
        (output / "acceptance-report.md").write_text(
            _acceptance_report(config, lifecycle, artifact), encoding="utf-8"
        )

    def _write_failed_outputs(
        self,
        config: AcceptanceConfig,
        lifecycle: Part3LifecycleResult,
        artifact: ArtifactInspectionBundle | None,
    ) -> None:
        output = config.output_directory.resolve()
        problem = lifecycle.vertical_slice.problem
        _write_json(
            output / "user-supplied-evidence.json",
            {
                "classification": "USER-SUPPLIED EVIDENCE",
                "status": "NOT_INGESTED_NO_LIVE_SUBJECT"
                if config.user_evidence_document
                else "NOT_SUPPLIED",
                "input_document_digest": sha256_digest(
                    dict(config.user_evidence_document)
                )
                if config.user_evidence_document
                else None,
                "behaviorally_validated": False,
            },
        )
        _write_json(
            output / "live-runtime-evidence.json",
            {
                "classification": "LIVE RUNTIME EVIDENCE",
                "status": "FAILED",
                "problem": _problem(problem),
                "evidence": [
                    _evidence(item)
                    for item in lifecycle.vertical_slice.discovery.evidence
                ],
            },
        )
        _write_json(
            output / "artifact-evidence.json",
            _artifact_document(artifact, None),
        )
        _write_json(
            output / "run-status.json",
            {
                "state": lifecycle.state,
                "approval_state": "NOT_REQUESTED",
                "approval_request_created": False,
                "package_digest": None,
                "sage_accessed": False,
                "registry_modified": False,
                "problem": _problem(problem),
            },
        )
        (output / "acceptance-report.md").write_text(
            "# Real Deployment Acceptance Report\n\n"
            "**Result:** `FAILED_BEFORE_DRAFT`\n\n"
            "No draft package or approval request was created.\n\n"
            f"Problem: `{problem.code if problem else 'UNKNOWN'}` — "
            f"{problem.message if problem else lifecycle.problem}\n",
            encoding="utf-8",
        )


def _operation_context(config, environment_id, clock):
    now = clock()
    return OperationContext(
        run_id=deterministic_id(
            "acceptance-run", config.endpoint, config.model_reference, now.isoformat()
        ),
        correlation_id=deterministic_id(
            "acceptance-correlation", config.endpoint, config.model_reference
        ),
        deadline=now + timedelta(minutes=30),
        policy_id="real-deployment-acceptance",
        policy_version="0.3.0",
        workspace_id=environment_id,
        allowed_permissions=(
            f"network:{config.endpoint}",
            "filesystem:acceptance-output-only",
        ),
        limits=ResourceLimits(
            timeout_seconds=config.timeout_seconds,
            max_output_bytes=4 * 1024 * 1024,
            max_memory_bytes=1024 * 1024 * 1024,
            max_disk_bytes=8 * 1024 * 1024 * 1024,
        ),
        cancellation=_NeverCancelled(),
    )


class _NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False

    async def wait(self) -> None:
        return None


def _endpoint_locality(endpoint: str) -> str:
    hostname = (urlparse(endpoint).hostname or "").lower()
    return "LOCAL" if hostname in {"localhost", "127.0.0.1", "::1"} else "REMOTE"


def _identity_document(lifecycle, artifact):
    identity = lifecycle.identity
    assert identity is not None
    direct_digest = artifact.gguf.observed.file_digest if artifact else None
    runtime_digest = lifecycle.vertical_slice.package.document["runtime"].get("model_digest")
    relation = (
        "NOT_AVAILABLE"
        if direct_digest is None
        else "DIGEST_EQUAL"
        if direct_digest == runtime_digest
        else "DISTINCT_DIGESTS_RELATION_UNVERIFIED"
    )
    return {
        "classification": "RUNTIME/MODEL COMPOSITION IDENTITY",
        "logical_model": _subject(identity.logical_model),
        "runtime_artifact": _subject(identity.artifact) if identity.artifact else None,
        "deployment": _subject(identity.deployment),
        "composition": _subject(identity.composition),
        "identity_status": identity.identity_status,
        "alias_collision": identity.alias_collision,
        "runtime_model_digest": runtime_digest,
        "direct_gguf_digest": direct_digest,
        "runtime_to_direct_artifact_relation": relation,
        "evidence": [_evidence(item) for item in identity.evidence],
    }


def _artifact_document(artifact, runtime_digest):
    if artifact is None:
        return {
            "classification": "ARTIFACT EVIDENCE",
            "status": "NOT_SUPPLIED",
            "runtime_model_digest": runtime_digest,
            "direct_artifact_digest": None,
            "evidence": [],
        }
    gguf = artifact.gguf
    interpreted = gguf.interpreted
    relation = (
        "DIGEST_EQUAL"
        if runtime_digest == gguf.observed.file_digest
        else "DISTINCT_DIGESTS_RELATION_UNVERIFIED"
        if runtime_digest
        else "RUNTIME_DIGEST_UNAVAILABLE"
    )
    return {
        "classification": "ARTIFACT EVIDENCE",
        "status": "DIRECT_GGUF_VERIFIED",
        "artifact": _subject(gguf.artifact),
        "file_digest": gguf.observed.file_digest,
        "file_size": gguf.observed.file_size,
        "runtime_model_digest": runtime_digest,
        "runtime_to_direct_artifact_relation": relation,
        "gguf": {
            "version": gguf.observed.version,
            "tensor_count": gguf.observed.tensor_count,
            "metadata_count": gguf.observed.metadata_count,
            "structural_issues": list(gguf.observed.structural_issues),
            "architecture": interpreted.architecture,
            "parameter_count_declared": interpreted.parameter_count_declared,
            "parameter_count_estimate": interpreted.parameter_count_estimate,
            "quantization_declared": interpreted.quantization_declared,
            "quantization_observed": list(interpreted.quantization_observed),
            "context_length_declared": interpreted.context_length,
            "embedding_length": interpreted.embedding_length,
            "layer_count": interpreted.layer_count,
            "attention": dict(interpreted.attention),
            "feed_forward": dict(interpreted.feed_forward),
        },
        "tokenizer": {
            "status": artifact.tokenizer.status,
            "type": artifact.tokenizer.tokenizer_type,
            "vocabulary_present": artifact.tokenizer.vocabulary_present,
            "vocabulary_size": artifact.tokenizer.vocabulary_size,
            "special_tokens": dict(artifact.tokenizer.special_tokens),
            "unknowns": list(artifact.tokenizer.unknowns),
        },
        "chat_template": {
            "status": artifact.template.status,
            "present": artifact.template.present,
            "digest": artifact.template.template_digest,
            "syntax": artifact.template.syntax,
            "possible_roles": list(artifact.template.possible_roles),
            "tool_syntax_hint": artifact.template.tool_syntax_hint,
            "structured_output_hint": artifact.template.structured_output_hint,
            "behavior_validated": False,
            "warnings": list(artifact.template.warnings),
        },
        "evidence": [_evidence(item) for item in artifact.evidence],
    }


def _probe_document(lifecycle):
    probes = lifecycle.vertical_slice.probes
    if probes is None:
        return {
            "classification": "BEHAVIORAL TEST EVIDENCE",
            "status": "NOT_PLANNED",
            "results": [],
        }
    actual = {item.raw.probe_id: item for item in probes.results}
    results = []
    for case in probes.plan.cases:
        result = actual.get(case.probe_id)
        if result is None:
            results.append(
                {
                    "probe_id": case.probe_id,
                    "kind": case.kind.value,
                    "capability_key": case.capability_key,
                    "subject": _subject(case.subject),
                    "outcome": "BLOCKED",
                    "reason": probes.problem.code
                    if probes.problem
                    else "NO_RESULT",
                    "evidence_id": None,
                }
            )
        else:
            results.append(
                {
                    "probe_id": case.probe_id,
                    "kind": case.kind.value,
                    "capability_key": case.capability_key,
                    "subject": _subject(case.subject),
                    "outcome": result.raw.outcome.value,
                    "assertions": dict(result.raw.assertions),
                    "measurements": dict(result.raw.measurements),
                    "output_digest": result.raw.output_digest,
                    "evidence_id": result.evidence_id,
                }
            )
    return {
        "classification": "BEHAVIORAL TEST EVIDENCE",
        "status": "BLOCKED_PRODUCTION_SANDBOX_UNAVAILABLE"
        if probes.problem
        else "EXECUTED",
        "production_security_boundary": False,
        "problem": _problem(probes.problem),
        "results": results,
    }


def _capability_document(capabilities):
    inferred = []
    unknown = []
    validated = []
    partial = []
    for item in capabilities:
        if item["validation"] == "VALIDATED":
            validated.append(item)
        if "INFERRED" in item["evidence_levels"]:
            inferred.append(item)
        if item["support"] in {"UNKNOWN", "CONFLICTING"}:
            unknown.append(item)
        if item["support"] == "PARTIAL":
            partial.append(item)
    return {
        "classification": "CAPABILITY EVIDENCE CLASSIFICATION",
        "all": capabilities,
        "behaviorally_validated": validated,
        "inferred_capabilities": inferred,
        "unknown_or_conflicting_capabilities": unknown,
        "partial_capabilities": partial,
    }


def _acceptance_report(config, lifecycle, artifact):
    proposed = lifecycle.proposed_package.document
    base = proposed["base_package"]
    probes = lifecycle.vertical_slice.probes
    blocked_count = len(probes.plan.cases) if probes and probes.problem else 0
    user_count = sum(1 for item in base["evidence"] if item["kind"] == "USER_INPUT")
    live_count = sum(
        1
        for item in base["evidence"]
        if item["collector_id"]
        in {
            "mie.discovery.ollama-api",
            "mie.inspector.ollama-model-details",
            "mie.inspector.tokenizer-metadata",
            "mie.inspector.chat-template",
        }
        and item["source"]["uri"].startswith(config.endpoint.rstrip("/"))
    )
    delta = lifecycle.vertical_slice.capability_delta
    artifact_status = "DIRECT_GGUF_VERIFIED" if artifact else "NOT_SUPPLIED"
    return f"""# Real Deployment Acceptance Report

**Lifecycle state:** `DRAFT_PENDING_APPROVAL`
**Approval state:** `NOT_REQUESTED`
**Approval request created:** `false`
**Runtime endpoint:** `{config.endpoint}`
**Runtime model reference:** `{config.model_reference}`
**Security verdict:** `{proposed['security_assessment']['verdict']}`

## USER-SUPPLIED EVIDENCE

Records: **{user_count}**. These records retain `kind=USER_INPUT` and are not behavioral validation.

## LIVE RUNTIME EVIDENCE

Records: **{live_count}** from the generic Ollama `/api/version`, `/api/tags`, and `/api/show` path. Responses are bound to source digests in `live-runtime-evidence.json`.

## ARTIFACT EVIDENCE

Status: `{artifact_status}`. Declared context or feature metadata is not promoted to usable behavioral capability.

## BEHAVIORAL TEST EVIDENCE

Status: `BLOCKED_PRODUCTION_SANDBOX_UNAVAILABLE`. Planned probes blocked: **{blocked_count}**. The reference subprocess backend was not used and no production-isolation claim was made.

## INFERRED CAPABILITIES

Metadata/runtime declarations remain hypotheses unless backed by passing `VALIDATED_BY_TEST` evidence. See `capability-assessment.json`.

## UNKNOWN/BLOCKED CAPABILITIES

Basic generation, deterministic instruction behavior, streaming, bounded context, structured output, tool calling, error handling, and timeout handling remain blocked for MIE-controlled validation in this run.

## Compatibility

Overall status: `{base['compatibility']['status']}`. Unknown mandatory requirements remain fail-closed.

## Capability delta

Status: `{delta.status if delta else 'UNKNOWN_NOT_COMPUTED'}`. The registry was read-only and was not modified.

## Draft package

Immutable package digest: `{lifecycle.submitted_package.package_digest}`. The package remains `DRAFT_PENDING_APPROVAL`; no approval, application, SAGE access, or global registration occurred.
"""


def _subject(value):
    return {
        "kind": value.kind.value,
        "subject_id": value.subject_id,
        "version": value.version,
        "digest": value.digest,
    }


def _evidence(value):
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
        "collected_at": value.collected_at.isoformat(),
        "outcome": value.outcome.value if value.outcome else None,
        "environment_id": value.environment_id,
        "derived_from": list(value.derived_from),
        "redacted": value.redacted,
    }


def _problem(value):
    if value is None:
        return None
    return {
        "code": value.code,
        "stage": value.stage.value,
        "message": value.message,
        "retryable": value.retryable,
        "remediation": list(value.remediation),
        "details": dict(value.details),
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_manifest(root: Path) -> None:
    manifest = root / "artifact-manifest.sha256"
    lines = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path == manifest:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  ./{path.relative_to(root).as_posix()}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_digest(value: str) -> None:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ValueError("artifact digest must use sha256:<64 lowercase hex>")
    if any(character not in "0123456789abcdef" for character in value[7:]):
        raise ValueError("artifact digest must use sha256:<64 lowercase hex>")
