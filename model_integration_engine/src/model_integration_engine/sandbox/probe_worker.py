"""Sandbox worker for live MIE behavioral probes.

The worker accepts exactly one ProbeWorkerSpec JSON document on stdin,
reconstructs the existing generic Ollama RuntimeAdapter, runs the existing
SafeProbeHarness, and writes the already-defined probe-results artifact.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..application.probes import RawProbeResult, SafeProbeHarness
from ..contracts import CancellationSignal, OperationContext
from ..plugins.ollama.adapter import OllamaAdapterConfig
from ..plugins.ollama.client import StdlibJsonTransport
from ..runtimes.ollama import OllamaRuntimePlugin
from .probe_worker_contract import ProbeWorkerSpec


@dataclass(slots=True)
class _NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False

    async def wait(self) -> None:
        await asyncio.Future()


def _operation_context(spec: ProbeWorkerSpec) -> OperationContext:
    context = spec.context
    cancellation: CancellationSignal = _NeverCancelled()
    return OperationContext(
        run_id=context.run_id,
        correlation_id=context.correlation_id,
        deadline=context.deadline,
        policy_id=context.policy_id,
        policy_version=context.policy_version,
        workspace_id=context.workspace_id,
        allowed_permissions=context.allowed_permissions,
        limits=context.limits,
        cancellation=cancellation,
    )


def _adapter_config(spec: ProbeWorkerSpec) -> OllamaAdapterConfig:
    raw = spec.adapter_configuration

    runtime_id = raw.get("runtime")
    deployment_id = raw.get("deployment")
    model_reference = raw.get("model_reference")
    configuration_digest = raw.get("configuration_digest")
    runtime_owns_template = raw.get("runtime_owns_template", True)

    if not isinstance(runtime_id, str) or not runtime_id:
        raise ValueError("adapter configuration runtime is required")
    if not isinstance(deployment_id, str) or not deployment_id:
        raise ValueError("adapter configuration deployment is required")
    if not isinstance(model_reference, str) or not model_reference:
        raise ValueError("adapter configuration model_reference is required")
    if not isinstance(configuration_digest, str) or not configuration_digest:
        raise ValueError("adapter configuration configuration_digest is required")
    if not isinstance(runtime_owns_template, bool):
        raise ValueError("adapter configuration runtime_owns_template is invalid")

    deployment = spec.plan.deployment
    runtime = spec.plan.runtime

    if runtime.subject_id != runtime_id:
        raise ValueError("adapter configuration runtime does not match plan")
    if deployment.subject_id != deployment_id:
        raise ValueError("adapter configuration deployment does not match plan")

    return OllamaAdapterConfig(
        runtime=runtime,
        deployment=deployment,
        model_reference=model_reference,
        configuration_digest=configuration_digest,
        runtime_owns_template=runtime_owns_template,
    )


def _result_document(result: RawProbeResult) -> dict[str, Any]:
    subject = result.subject
    return {
        "probe_id": result.probe_id,
        "kind": result.kind.value,
        "subject": {
            "kind": subject.kind.value,
            "subject_id": subject.subject_id,
            "version": subject.version,
            "digest": subject.digest,
        },
        "outcome": result.outcome.value,
        "assertions": dict(result.assertions),
        "measurements": dict(result.measurements),
        "output_digest": result.output_digest,
        "error_code": result.error_code,
        "error_message": result.error_message,
    }


def _write_results(spec: ProbeWorkerSpec, results: tuple[RawProbeResult, ...]) -> None:
    document = {
        "schema_version": "0.3.0",
        "plan_id": spec.plan.plan_id,
        "run_id": spec.run_id,
        "results": [_result_document(result) for result in results],
    }

    output = Path(spec.output_artifact_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


async def _run(spec: ProbeWorkerSpec) -> None:
    context = _operation_context(spec)
    adapter_config = _adapter_config(spec)

    plugin = OllamaRuntimePlugin(
        transport=StdlibJsonTransport(),
        timeout_seconds=context.limits.timeout_seconds,
    )
    adapter = plugin.create_adapter(spec.runtime_locator, adapter_config)

    results = await SafeProbeHarness().run_plan(
        spec.plan,
        adapter,
        context,
    )

    if {item.probe_id for item in results} != {
        item.probe_id for item in spec.plan.cases
    }:
        raise RuntimeError("probe worker returned an unexpected probe set")

    _write_results(spec, results)


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            raise ValueError("probe worker stdin is empty")

        document = json.loads(raw)
        spec = ProbeWorkerSpec.from_document(document)

        asyncio.run(_run(spec))
        return 0

    except Exception as exc:
        print(
            f"probe-worker-failed: {type(exc).__name__}: {str(exc)[:500]}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
