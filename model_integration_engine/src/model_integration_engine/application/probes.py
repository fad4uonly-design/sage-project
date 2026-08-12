"""Safe minimal probe plan and sandbox-bound execution coordinator.

`SafeProbeHarness` contains the non-destructive test logic intended to execute
inside an implementation of `ProbeExecutionBackend`. The coordinator refuses to
promote results unless the backend attests the mandatory isolation controls.
Tests use a deterministic backend; no in-process backend is offered for live use.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ..contracts import (
    InferenceRequest,
    Message,
    MessagePart,
    OperationContext,
    RuntimeAdapter,
    ToolDefinition,
)
from ..domain import (
    CapabilityClaim,
    CapabilityClass,
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    EvidenceRecord,
    JSONValue,
    ProblemDetails,
    SubjectRef,
    SupportState,
    TestOutcome,
    ValidationState,
    WorkflowStage,
)
from ..evidence import EvidenceFactory, deterministic_id, sha256_digest, utc_now


class ProbeKind(StrEnum):
    BASIC_GENERATION = "BASIC_GENERATION"
    INSTRUCTION_FOLLOWING = "INSTRUCTION_FOLLOWING"
    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    STREAMING = "STREAMING"
    TOOL_CALLING = "TOOL_CALLING"
    CONTEXT_HANDLING = "CONTEXT_HANDLING"
    MULTIMODAL_INPUT = "MULTIMODAL_INPUT"
    ERROR_HANDLING = "ERROR_HANDLING"
    TIMEOUT_HANDLING = "TIMEOUT_HANDLING"


PROBE_CAPABILITY = {
    ProbeKind.BASIC_GENERATION: "generation.text",
    ProbeKind.INSTRUCTION_FOLLOWING: "instruction.following",
    ProbeKind.STRUCTURED_OUTPUT: "output.schema_constrained",
    ProbeKind.STREAMING: "protocol.streaming",
    ProbeKind.TOOL_CALLING: "tools.function_calling",
    ProbeKind.CONTEXT_HANDLING: "context.handling",
    ProbeKind.MULTIMODAL_INPUT: "modality.vision.input",
    ProbeKind.ERROR_HANDLING: "failure.invalid_input",
    ProbeKind.TIMEOUT_HANDLING: "failure.timeout",
}


@dataclass(frozen=True, slots=True)
class ProbeCase:
    probe_id: str
    kind: ProbeKind
    capability_key: str
    subject: SubjectRef
    fixture_digest: str


@dataclass(frozen=True, slots=True)
class ProbePlan:
    plan_id: str
    suite_id: str
    suite_version: str
    deployment: SubjectRef
    runtime: SubjectRef
    adapter_id: str
    configuration_digest: str
    environment_id: str
    cases: tuple[ProbeCase, ...]
    required_controls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RawProbeResult:
    probe_id: str
    kind: ProbeKind
    subject: SubjectRef
    outcome: TestOutcome
    assertions: Mapping[str, JSONValue]
    measurements: Mapping[str, JSONValue]
    output_digest: str | None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class IsolationAttestation:
    run_id: str
    backend_id: str
    backend_version: str
    job_digest: str
    isolated: bool
    requested_controls: tuple[str, ...]
    enforced_controls: tuple[str, ...]
    missing_controls: tuple[str, ...]
    allowed_endpoints: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    host_write_observed: bool
    cleanup_complete: bool


@dataclass(frozen=True, slots=True)
class BackendProbeBatch:
    results: tuple[RawProbeResult, ...]
    attestation: IsolationAttestation


@dataclass(frozen=True, slots=True)
class ProbeResult:
    raw: RawProbeResult
    evidence_id: str


@dataclass(frozen=True, slots=True)
class ProbeBatchResult:
    plan: ProbePlan
    results: tuple[ProbeResult, ...]
    evidence: tuple[EvidenceRecord, ...]
    attestation: IsolationAttestation | None
    claims: tuple[CapabilityClaim, ...]
    problem: ProblemDetails | None = None


class ProbeExecutionBackend(Protocol):
    async def execute(
        self,
        plan: ProbePlan,
        harness: "SafeProbeHarness",
        adapter: RuntimeAdapter,
        context: OperationContext,
    ) -> BackendProbeBatch: ...


@dataclass(slots=True)
class BlockedProbeExecutionBackend:
    """Truthfully represent unavailable production probe isolation.

    This backend executes nothing.  It returns an attestation with every
    required control missing so ``ProbeCoordinator`` records the existing
    ``SANDBOX_CONTROL_UNAVAILABLE`` blocker and promotes no behavioral result.
    """

    reason: str = "No production-qualified probe backend is configured."
    backend_id: str = "mie.probes.blocked-production-unavailable"
    backend_version: str = "0.3.0"
    clock: callable = utc_now

    async def execute(
        self,
        plan: ProbePlan,
        harness: "SafeProbeHarness",
        adapter: RuntimeAdapter,
        context: OperationContext,
    ) -> BackendProbeBatch:
        started = self.clock()
        job_digest = sha256_digest(
            {
                "plan_id": plan.plan_id,
                "backend_id": self.backend_id,
                "status": "BLOCKED",
                "reason": self.reason,
            }
        )
        return BackendProbeBatch(
            results=(),
            attestation=IsolationAttestation(
                run_id=deterministic_id("blocked-probe-run", plan.plan_id),
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                job_digest=job_digest,
                isolated=False,
                requested_controls=plan.required_controls,
                enforced_controls=(),
                missing_controls=plan.required_controls,
                allowed_endpoints=(),
                started_at=started,
                completed_at=self.clock(),
                host_write_observed=False,
                cleanup_complete=True,
            ),
        )


@dataclass(slots=True)
class MinimalProbePlanner:
    suite_version: str = "0.2.0"

    def plan(
        self,
        *,
        deployment: SubjectRef,
        runtime: SubjectRef,
        adapter_id: str,
        configuration_digest: str,
        environment_id: str,
        hypotheses: tuple[CapabilityClaim, ...],
        include_operational_probes: bool = False,
    ) -> ProbePlan:
        by_key = {claim.capability_key: claim for claim in hypotheses}
        kinds = [
            ProbeKind.BASIC_GENERATION,
            ProbeKind.INSTRUCTION_FOLLOWING,
            ProbeKind.STRUCTURED_OUTPUT,
            ProbeKind.STREAMING,
        ]
        if include_operational_probes:
            kinds.extend(
                (ProbeKind.ERROR_HANDLING, ProbeKind.TIMEOUT_HANDLING)
            )
        tool_claim = by_key.get("tools.function_calling")
        if tool_claim and tool_claim.support is SupportState.SUPPORTED:
            kinds.append(ProbeKind.TOOL_CALLING)
        context_claim = by_key.get("context.long")
        if context_claim and context_claim.support is SupportState.SUPPORTED:
            kinds.append(ProbeKind.CONTEXT_HANDLING)
        vision_claim = by_key.get("modality.vision.input")
        if vision_claim and vision_claim.support is SupportState.SUPPORTED:
            kinds.append(ProbeKind.MULTIMODAL_INPUT)

        cases = []
        for kind in kinds:
            subject = runtime if kind is ProbeKind.STREAMING else deployment
            fixture = _fixture_for(kind)
            cases.append(
                ProbeCase(
                    probe_id=deterministic_id(
                        "probe", deployment.subject_id, kind.value, self.suite_version
                    ),
                    kind=kind,
                    capability_key=PROBE_CAPABILITY[kind],
                    subject=subject,
                    fixture_digest=sha256_digest(fixture),
                )
            )
        plan_material = {
            "suite_version": self.suite_version,
            "deployment": deployment.subject_id,
            "runtime": runtime.subject_id,
            "adapter_id": adapter_id,
            "configuration_digest": configuration_digest,
            "environment_id": environment_id,
            "cases": [case.probe_id for case in cases],
        }
        return ProbePlan(
            plan_id=deterministic_id("probe-plan", plan_material),
            suite_id="mie.safe-vertical-slice",
            suite_version=self.suite_version,
            deployment=deployment,
            runtime=runtime,
            adapter_id=adapter_id,
            configuration_digest=configuration_digest,
            environment_id=environment_id,
            cases=tuple(cases),
            required_controls=(
                "read_only_inputs",
                "ephemeral_scratch",
                "network_allowlist",
                "no_target_mount",
                "resource_limits",
            ),
        )


@dataclass(slots=True)
class SafeProbeHarness:
    """Non-destructive probe logic intended to run within a sandbox backend."""

    async def run_case(
        self,
        case: ProbeCase,
        plan: ProbePlan,
        adapter: RuntimeAdapter,
        context: OperationContext,
    ) -> RawProbeResult:
        try:
            if case.kind is ProbeKind.BASIC_GENERATION:
                return await self._basic(case, plan, adapter, context)
            if case.kind is ProbeKind.INSTRUCTION_FOLLOWING:
                return await self._instruction(case, plan, adapter, context)
            if case.kind is ProbeKind.STRUCTURED_OUTPUT:
                return await self._structured(case, plan, adapter, context)
            if case.kind is ProbeKind.STREAMING:
                return await self._streaming(case, plan, adapter, context)
            if case.kind is ProbeKind.TOOL_CALLING:
                return await self._tool_call(case, plan, adapter, context)
            if case.kind is ProbeKind.CONTEXT_HANDLING:
                return await self._context(case, plan, adapter, context)
            if case.kind is ProbeKind.MULTIMODAL_INPUT:
                return await self._multimodal(case, plan, adapter, context)
            if case.kind is ProbeKind.ERROR_HANDLING:
                return await self._error_handling(case, plan, adapter, context)
            if case.kind is ProbeKind.TIMEOUT_HANDLING:
                return await self._timeout_handling(case, plan, adapter, context)
            raise ValueError(f"Unknown probe kind: {case.kind}")
        except Exception as exc:  # one failed probe must not abort the batch
            return RawProbeResult(
                probe_id=case.probe_id,
                kind=case.kind,
                subject=case.subject,
                outcome=TestOutcome.ERROR,
                assertions={"unambiguous": False},
                measurements={},
                output_digest=None,
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
            )

    async def run_plan(
        self,
        plan: ProbePlan,
        adapter: RuntimeAdapter,
        context: OperationContext,
    ) -> tuple[RawProbeResult, ...]:
        results = []
        for case in plan.cases:
            results.append(await self.run_case(case, plan, adapter, context))
        return tuple(results)

    def _request(
        self,
        case: ProbeCase,
        plan: ProbePlan,
        prompt: str,
        *,
        response_schema: Mapping[str, JSONValue] | None = None,
        tools: tuple[ToolDefinition, ...] = (),
    ) -> InferenceRequest:
        return InferenceRequest(
            operation_id=case.probe_id,
            deployment=plan.deployment,
            messages=(
                Message(role="user", parts=(MessagePart(kind="text", value=prompt),)),
            ),
            tools=tools,
            response_schema=response_schema,
            generation={"temperature": 0},
            maximum_output_tokens=64,
            retain_raw_output=False,
        )

    async def _basic(self, case, plan, adapter, context) -> RawProbeResult:
        expected = "MIE_BASIC_OK_7A31"
        request = self._request(
            case, plan, f"Return exactly this token and nothing else: {expected}"
        )
        response = await adapter.infer(request, context)
        text = _response_text(response.output_parts)
        passed = text.strip() == expected
        return _result(case, passed, {"exact_token": passed}, text)

    async def _instruction(self, case, plan, adapter, context) -> RawProbeResult:
        expected = "ALPHA-29"
        request = self._request(
            case,
            plan,
            "Follow this instruction exactly. Convert 'alpha-29' to uppercase and "
            "return only the converted value.",
        )
        response = await adapter.infer(request, context)
        text = _response_text(response.output_parts)
        passed = text.strip() == expected
        return _result(case, passed, {"instruction_exact": passed}, text)

    async def _structured(self, case, plan, adapter, context) -> RawProbeResult:
        nonce = "schema-41"
        schema: Mapping[str, JSONValue] = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["ok"]},
                "nonce": {"type": "string", "enum": [nonce]},
            },
            "required": ["status", "nonce"],
            "additionalProperties": False,
        }
        request = self._request(
            case,
            plan,
            f"Return an object with status ok and nonce {nonce}.",
            response_schema=schema,
        )
        response = await adapter.infer(request, context)
        text = _response_text(response.output_parts)
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = None
        passed = value == {"status": "ok", "nonce": nonce}
        return _result(
            case,
            passed,
            {"valid_json": value is not None, "schema_exact": passed},
            text,
        )

    async def _streaming(self, case, plan, adapter, context) -> RawProbeResult:
        expected = "MIE_STREAM_OK_62"
        request = self._request(
            case, plan, f"Return exactly this token and nothing else: {expected}"
        )
        chunks = []
        terminal_count = 0
        event_count = 0
        async for event in adapter.stream(request, context):
            event_count += 1
            if isinstance(event.data, Mapping):
                content = event.data.get("content")
                if isinstance(content, str):
                    chunks.append(content)
            if event.terminal:
                terminal_count += 1
        text = "".join(chunks)
        passed = text.strip() == expected and terminal_count == 1 and event_count >= 2
        return _result(
            case,
            passed,
            {
                "assembled_exact": text.strip() == expected,
                "single_terminal": terminal_count == 1,
                "multiple_events": event_count >= 2,
            },
            text,
            measurements={"event_count": event_count},
        )

    async def _tool_call(self, case, plan, adapter, context) -> RawProbeResult:
        value = "tool-73"
        tool = ToolDefinition(
            name="mie_echo",
            description="Return the supplied value. This is a side-effect-free test tool.",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )
        request = self._request(
            case,
            plan,
            f"Call mie_echo exactly once with value {value}. Do not answer directly.",
            tools=(tool,),
        )
        response = await adapter.infer(request, context)
        passed = (
            len(response.tool_calls) == 1
            and response.tool_calls[0].name == "mie_echo"
            and dict(response.tool_calls[0].arguments) == {"value": value}
        )
        return RawProbeResult(
            probe_id=case.probe_id,
            kind=case.kind,
            subject=case.subject,
            outcome=TestOutcome.PASS if passed else TestOutcome.FAIL,
            assertions={"single_exact_tool_call": passed, "unambiguous": passed},
            measurements={"tool_call_count": len(response.tool_calls)},
            output_digest=response.raw_response_digest,
        )

    async def _context(self, case, plan, adapter, context) -> RawProbeResult:
        canary = "CTX_CANARY_4F91"
        filler = "bounded-context-fixture " * 180
        prompt = (
            f"Remember the first token {canary}.\n{filler}\n"
            "Return only the first token now."
        )
        request = self._request(case, plan, prompt)
        response = await adapter.infer(request, context)
        text = _response_text(response.output_parts)
        passed = text.strip() == canary
        return _result(
            case,
            passed,
            {"retrieved_canary": passed},
            text,
            measurements={"input_characters": len(prompt)},
        )

    async def _multimodal(self, case, plan, adapter, context) -> RawProbeResult:
        # A tiny deterministic PNG fixture; no external file/network access.
        red_pixel_png = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB"
            "9Y9Z4QAAAABJRU5ErkJggg=="
        )
        request = InferenceRequest(
            operation_id=case.probe_id,
            deployment=plan.deployment,
            messages=(
                Message(
                    role="user",
                    parts=(
                        MessagePart(kind="text", value="Name the pixel color using one lowercase word."),
                        MessagePart(kind="image_base64", value=red_pixel_png, media_type="image/png"),
                    ),
                ),
            ),
            generation={"temperature": 0},
            maximum_output_tokens=16,
            retain_raw_output=False,
        )
        response = await adapter.infer(request, context)
        text = _response_text(response.output_parts)
        passed = text.strip().lower() == "red"
        return _result(
            case,
            passed,
            {"recognized_expected_color": passed},
            text,
            measurements={"image_count": 1, "media_type": "image/png"},
        )

    async def _error_handling(self, case, plan, adapter, context) -> RawProbeResult:
        """Validate deterministic rejection of an unsupported normalized part.

        This is an adapter/integration contract check.  It does not establish a
        model capability and it deliberately supplies no consequential input.
        """

        request = InferenceRequest(
            operation_id=case.probe_id,
            deployment=plan.deployment,
            messages=(
                Message(
                    role="user",
                    parts=(
                        MessagePart(
                            kind="unsupported_acceptance_fixture", value="reject-me"
                        ),
                    ),
                ),
            ),
            maximum_output_tokens=1,
            retain_raw_output=False,
        )
        try:
            await adapter.infer(request, context)
        except Exception as exc:
            error_type = type(exc).__name__
            return RawProbeResult(
                probe_id=case.probe_id,
                kind=case.kind,
                subject=case.subject,
                outcome=TestOutcome.PASS,
                assertions={
                    "unsupported_input_rejected": True,
                    "unambiguous": True,
                },
                measurements={"error_type": error_type},
                output_digest=sha256_digest(
                    {"contract": "unsupported-input-rejection", "error_type": error_type}
                ),
            )
        return RawProbeResult(
            probe_id=case.probe_id,
            kind=case.kind,
            subject=case.subject,
            outcome=TestOutcome.FAIL,
            assertions={
                "unsupported_input_rejected": False,
                "unambiguous": False,
            },
            measurements={},
            output_digest=sha256_digest("unsupported-input-was-accepted"),
        )

    async def _timeout_handling(self, case, plan, adapter, context) -> RawProbeResult:
        """Exercise a bounded client deadline inside the sandbox worker.

        A pass validates only client-visible deadline enforcement for this
        request profile.  It does not prove server-side cancellation.
        """

        request = self._request(
            case,
            plan,
            "Return exactly the token MIE_TIMEOUT_FIXTURE and nothing else.",
        )
        timeout_seconds = min(
            0.05, max(0.001, context.limits.timeout_seconds / 1000.0)
        )
        try:
            await asyncio.wait_for(
                adapter.infer(request, context), timeout=timeout_seconds
            )
        except TimeoutError:
            return RawProbeResult(
                probe_id=case.probe_id,
                kind=case.kind,
                subject=case.subject,
                outcome=TestOutcome.PASS,
                assertions={
                    "client_deadline_enforced": True,
                    "server_cancellation_proven": False,
                    "unambiguous": True,
                },
                measurements={"timeout_seconds": timeout_seconds},
                output_digest=sha256_digest(
                    {"contract": "client-deadline", "timeout": timeout_seconds}
                ),
            )
        except Exception as exc:
            return RawProbeResult(
                probe_id=case.probe_id,
                kind=case.kind,
                subject=case.subject,
                outcome=TestOutcome.ERROR,
                assertions={"unambiguous": False},
                measurements={"timeout_seconds": timeout_seconds},
                output_digest=None,
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
            )
        return RawProbeResult(
            probe_id=case.probe_id,
            kind=case.kind,
            subject=case.subject,
            outcome=TestOutcome.FAIL,
            assertions={
                "client_deadline_enforced": False,
                "server_cancellation_proven": False,
                "unambiguous": False,
            },
            measurements={"timeout_seconds": timeout_seconds},
            output_digest=sha256_digest("request-completed-before-timeout"),
        )


def _fixture_for(kind: ProbeKind) -> Mapping[str, JSONValue]:
    return {
        "kind": kind.value,
        "safe": True,
        "network_side_effects": False,
        "target_access": False,
        "suite": "mie.safe-vertical-slice@0.2.0",
    }


def _response_text(parts) -> str:
    return "".join(
        part.value
        for part in parts
        if part.kind == "text" and isinstance(part.value, str)
    )


def _result(
    case: ProbeCase,
    passed: bool,
    assertions: Mapping[str, JSONValue],
    output: str,
    *,
    measurements: Mapping[str, JSONValue] | None = None,
) -> RawProbeResult:
    return RawProbeResult(
        probe_id=case.probe_id,
        kind=case.kind,
        subject=case.subject,
        outcome=TestOutcome.PASS if passed else TestOutcome.FAIL,
        assertions={**assertions, "unambiguous": passed},
        measurements=measurements or {},
        output_digest=sha256_digest(output.encode("utf-8")),
    )


@dataclass(slots=True)
class ProbeCoordinator:
    backend: ProbeExecutionBackend
    clock: callable = utc_now

    async def execute(
        self,
        *,
        plan: ProbePlan,
        harness: SafeProbeHarness,
        adapter: RuntimeAdapter,
        context: OperationContext,
        hypotheses: tuple[CapabilityClaim, ...],
    ) -> ProbeBatchResult:
        try:
            backend_batch = await self.backend.execute(plan, harness, adapter, context)
        except Exception as exc:
            return ProbeBatchResult(
                plan=plan,
                results=(),
                evidence=(),
                attestation=None,
                claims=hypotheses,
                problem=ProblemDetails(
                    code="PROBE_BACKEND_FAILED",
                    stage=WorkflowStage.SANDBOXED,
                    message=str(exc)[:500],
                    retryable=True,
                    subject=plan.deployment,
                    remediation=("Inspect sandbox backend and retry the probe plan.",),
                ),
            )

        attestation = backend_batch.attestation
        missing = set(plan.required_controls) - set(attestation.enforced_controls)
        isolation_valid = (
            attestation.isolated
            and not missing
            and not attestation.host_write_observed
            and attestation.cleanup_complete
        )
        if not isolation_valid:
            return ProbeBatchResult(
                plan=plan,
                results=(),
                evidence=(),
                attestation=attestation,
                claims=hypotheses,
                problem=ProblemDetails(
                    code="SANDBOX_CONTROL_UNAVAILABLE",
                    stage=WorkflowStage.SANDBOXED,
                    message="Mandatory probe isolation controls were not enforced.",
                    retryable=False,
                    subject=plan.deployment,
                    remediation=("Use a backend that enforces every mandatory control.",),
                    details={"missing_controls": sorted(missing)},
                    cleanup_complete=attestation.cleanup_complete,
                ),
            )

        factory = EvidenceFactory(
            "mie.probes.safe-vertical-slice", plan.suite_version, self.clock
        )
        evidence: list[EvidenceRecord] = []
        isolation_evidence = factory.create(
            kind=EvidenceKind.RUNTIME_OBSERVATION,
            level=EvidenceLevel.DETECTED_FROM_RUNTIME,
            subject=plan.deployment,
            observation_key="sandbox.isolation_attestation",
            observed_value={
                "backend_id": attestation.backend_id,
                "backend_version": attestation.backend_version,
                "enforced_controls": list(attestation.enforced_controls),
                "host_write_observed": attestation.host_write_observed,
                "cleanup_complete": attestation.cleanup_complete,
            },
            source_uri=f"sandbox://{attestation.backend_id}/{attestation.run_id}",
            source_digest=attestation.job_digest,
            locator="/attestation",
            outcome=EvidenceOutcome.PASS,
            environment_id=plan.environment_id,
        )
        evidence.append(isolation_evidence)

        results: list[ProbeResult] = []
        for raw in backend_batch.results:
            outcome = {
                TestOutcome.PASS: EvidenceOutcome.PASS,
                TestOutcome.FAIL: EvidenceOutcome.FAIL,
                TestOutcome.ERROR: EvidenceOutcome.ERROR,
                TestOutcome.INCONCLUSIVE: EvidenceOutcome.INCONCLUSIVE,
                TestOutcome.SKIPPED: EvidenceOutcome.NOT_APPLICABLE,
            }[raw.outcome]
            level = (
                EvidenceLevel.VALIDATED_BY_TEST
                if raw.outcome is TestOutcome.PASS
                else EvidenceLevel.UNKNOWN
            )
            item = factory.create(
                kind=EvidenceKind.TEST_RESULT,
                level=level,
                subject=raw.subject,
                observation_key=f"probe.{raw.kind.value.lower()}",
                observed_value={
                    "assertions": dict(raw.assertions),
                    "measurements": dict(raw.measurements),
                    "error_code": raw.error_code,
                    "error_message": raw.error_message,
                    "adapter_id": plan.adapter_id,
                    "configuration_digest": plan.configuration_digest,
                },
                source_uri=f"sandbox://{attestation.backend_id}/{attestation.run_id}/{raw.probe_id}",
                source_digest=raw.output_digest or attestation.job_digest,
                locator="/result",
                outcome=outcome,
                environment_id=plan.environment_id,
                redacted=True,
            )
            evidence.append(item)
            results.append(ProbeResult(raw=raw, evidence_id=item.evidence_id))

        claims = _apply_probe_results(
            hypotheses,
            tuple(results),
            plan=plan,
            assessed_at=self.clock(),
        )
        return ProbeBatchResult(
            plan=plan,
            results=tuple(results),
            evidence=tuple(evidence),
            attestation=attestation,
            claims=claims,
        )


def _apply_probe_results(
    hypotheses: tuple[CapabilityClaim, ...],
    results: tuple[ProbeResult, ...],
    *,
    plan: ProbePlan,
    assessed_at: datetime,
) -> tuple[CapabilityClaim, ...]:
    by_key = {claim.capability_key: claim for claim in hypotheses}
    for result in results:
        key = PROBE_CAPABILITY[result.raw.kind]
        prior = by_key.get(key)
        evidence_ids = (prior.evidence_ids if prior else ()) + (result.evidence_id,)
        evidence_levels = list(prior.evidence_levels if prior else ())
        if result.raw.outcome is TestOutcome.PASS:
            if EvidenceLevel.VALIDATED_BY_TEST not in evidence_levels:
                evidence_levels.append(EvidenceLevel.VALIDATED_BY_TEST)
            support = SupportState.SUPPORTED
            validation = ValidationState.VALIDATED
            contradictions = prior.contradictions if prior else ()
        else:
            if EvidenceLevel.UNKNOWN not in evidence_levels:
                evidence_levels.append(EvidenceLevel.UNKNOWN)
            validation = ValidationState.FAILED
            if prior and prior.support is SupportState.SUPPORTED:
                support = SupportState.CONFLICTING
                contradictions = (result.evidence_id,)
            else:
                support = SupportState.UNKNOWN
                contradictions = prior.contradictions if prior else ()

        subject = result.raw.subject
        by_key[key] = CapabilityClaim(
            claim_id=prior.claim_id
            if prior
            else deterministic_id("claim", subject.subject_id, key, plan.suite_version),
            capability_key=key,
            capability_class=prior.capability_class
            if prior
            else (
                CapabilityClass.RUNTIME_CAPABILITY
                if result.raw.kind is ProbeKind.STREAMING
                else CapabilityClass.INTEGRATION_CAPABILITY
                if result.raw.kind
                in {ProbeKind.ERROR_HANDLING, ProbeKind.TIMEOUT_HANDLING}
                else CapabilityClass.MODEL_CAPABILITY
            ),
            subject=subject,
            support=support,
            validation=validation,
            evidence_levels=tuple(evidence_levels),
            evidence_ids=evidence_ids,
            parameters={
                **(dict(prior.parameters) if prior else {}),
                "adapter_id": plan.adapter_id,
                "configuration_digest": plan.configuration_digest,
                "environment_id": plan.environment_id,
                "probe_id": result.raw.probe_id,
            },
            limitations=(prior.limitations if prior else ())
            + (
                ("Validated only under the recorded probe profile.",)
                if validation is ValidationState.VALIDATED
                else ("Probe did not produce unambiguous validation.",)
            ),
            contradictions=contradictions,
            policy_version=f"probe-policy-{plan.suite_version}",
            assessed_at=assessed_at,
        )
    return tuple(sorted(by_key.values(), key=lambda claim: claim.capability_key))
