from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from model_integration_engine.application.probes import (
    BackendProbeBatch,
    IsolationAttestation,
)
from model_integration_engine.contracts import OperationContext, ResourceLimits
from model_integration_engine.domain import JSONValue
from model_integration_engine.evidence import sha256_digest
from model_integration_engine.plugins.ollama.client import OllamaUnavailableError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ollama"
FIXED_NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def fixed_clock() -> datetime:
    return FIXED_NOW


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False

    async def wait(self) -> None:
        return None


def operation_context() -> OperationContext:
    return OperationContext(
        run_id="phase2-fixture-run",
        correlation_id="phase2-fixture-correlation",
        deadline=FIXED_NOW + timedelta(minutes=10),
        policy_id="phase2-test-policy",
        policy_version="0.2.0",
        workspace_id="fixture-workspace",
        allowed_permissions=(
            "network:http://fixture-ollama.invalid:11434",
            "filesystem:engine-workspace-only",
        ),
        limits=ResourceLimits(
            timeout_seconds=60,
            max_output_bytes=1_000_000,
            max_memory_bytes=512 * 1024 * 1024,
            max_disk_bytes=64 * 1024 * 1024,
        ),
        cancellation=NeverCancelled(),
    )


class FixtureTransport:
    def __init__(
        self,
        *,
        version=None,
        tags=None,
        show=None,
        unavailable: bool = False,
        fail_prompt_markers: tuple[str, ...] = (),
        malformed_chat: bool = False,
    ) -> None:
        self.version_value = copy.deepcopy(version if version is not None else load_fixture("version.json"))
        self.tags_value = copy.deepcopy(tags if tags is not None else load_fixture("tags.json"))
        self.show_value = copy.deepcopy(show if show is not None else load_fixture("show.json"))
        self.unavailable = unavailable
        self.fail_prompt_markers = fail_prompt_markers
        self.malformed_chat = malformed_chat
        self.calls: list[tuple[str, str, Mapping[str, JSONValue] | None]] = []

    async def request_json(
        self,
        method: str,
        url: str,
        body: Mapping[str, JSONValue] | None = None,
        *,
        timeout_seconds: float,
    ) -> Mapping[str, JSONValue]:
        self.calls.append((method, url, copy.deepcopy(body)))
        if self.unavailable:
            raise OllamaUnavailableError(
                "RUNTIME_UNREACHABLE",
                "fixture endpoint unavailable",
                retryable=True,
            )
        if url.endswith("/api/version"):
            return copy.deepcopy(self.version_value)
        if url.endswith("/api/tags"):
            return copy.deepcopy(self.tags_value)
        if url.endswith("/api/show"):
            return copy.deepcopy(self.show_value)
        if url.endswith("/api/chat"):
            if self.malformed_chat:
                return {"message": "not-an-object", "done": True}
            return self._chat_response(body or {})
        raise AssertionError(f"unexpected fixture URL: {url}")

    def _chat_response(self, body: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]:
        messages = body.get("messages")
        prompt = ""
        if isinstance(messages, list):
            for message in messages:
                if isinstance(message, dict) and message.get("role") == "user":
                    content = message.get("content")
                    if isinstance(content, str):
                        prompt = content
        if any(marker in prompt for marker in self.fail_prompt_markers):
            raise RuntimeError("fixture probe failure")

        message: dict[str, JSONValue] = {"role": "assistant", "content": ""}
        if "MIE_BASIC_OK_7A31" in prompt:
            message["content"] = "MIE_BASIC_OK_7A31"
        elif "alpha-29" in prompt:
            message["content"] = "ALPHA-29"
        elif "schema-41" in prompt:
            message["content"] = json.dumps({"status": "ok", "nonce": "schema-41"})
        elif "CTX_CANARY_4F91" in prompt:
            message["content"] = "CTX_CANARY_4F91"
        elif "pixel color" in prompt:
            message["content"] = "red"
        elif "mie_echo" in prompt:
            message["tool_calls"] = [
                {
                    "id": "fixture-call-1",
                    "function": {
                        "name": "mie_echo",
                        "arguments": {"value": "tool-73"},
                    },
                }
            ]
        else:
            message["content"] = "fixture response"
        return {
            "model": body.get("model", "fixture"),
            "message": message,
            "done": True,
            "done_reason": "stop",
            "total_duration": 1000,
            "load_duration": 100,
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

    async def stream_ndjson(
        self,
        method: str,
        url: str,
        body: Mapping[str, JSONValue],
        *,
        timeout_seconds: float,
    ) -> AsyncIterator[Mapping[str, JSONValue]]:
        self.calls.append((method, url, copy.deepcopy(body)))
        if self.unavailable:
            raise OllamaUnavailableError(
                "RUNTIME_UNREACHABLE",
                "fixture endpoint unavailable",
                retryable=True,
            )
        yield {
            "message": {"role": "assistant", "content": "MIE_STREAM_"},
            "done": False,
        }
        yield {
            "message": {"role": "assistant", "content": "OK_62"},
            "done": True,
            "done_reason": "stop",
        }


class DeterministicProbeBackend:
    """Test double for the sandbox port; never use as a live-isolation claim."""

    backend_id = "deterministic-fixture-sandbox"

    async def execute(self, plan, harness, adapter, context):
        results = await harness.run_plan(plan, adapter, context)
        attestation = IsolationAttestation(
            run_id="fixture-sandbox-run",
            backend_id=self.backend_id,
            backend_version="test-double-1",
            job_digest=sha256_digest(
                {"plan": plan.plan_id, "backend": self.backend_id}
            ),
            isolated=True,
            requested_controls=plan.required_controls,
            enforced_controls=plan.required_controls,
            missing_controls=(),
            allowed_endpoints=("http://fixture-ollama.invalid:11434",),
            started_at=FIXED_NOW,
            completed_at=FIXED_NOW + timedelta(seconds=1),
            host_write_observed=False,
            cleanup_complete=True,
        )
        return BackendProbeBatch(results=results, attestation=attestation)


class MissingControlsProbeBackend(DeterministicProbeBackend):
    async def execute(self, plan, harness, adapter, context):
        batch = await super().execute(plan, harness, adapter, context)
        attestation = IsolationAttestation(
            run_id=batch.attestation.run_id,
            backend_id=batch.attestation.backend_id,
            backend_version=batch.attestation.backend_version,
            job_digest=batch.attestation.job_digest,
            isolated=False,
            requested_controls=plan.required_controls,
            enforced_controls=("read_only_inputs",),
            missing_controls=tuple(plan.required_controls[1:]),
            allowed_endpoints=(),
            started_at=batch.attestation.started_at,
            completed_at=batch.attestation.completed_at,
            host_write_observed=False,
            cleanup_complete=True,
        )
        return BackendProbeBatch(results=batch.results, attestation=attestation)
