"""Capability Integration Loop tests.

Deterministic unit tests (no engine boot, no network, no live model): a bare
Container with duck-typed doubles proves that the orchestrator's capability
selection routes each request class to the EXISTING SAGE subsystem —

    memory      → MemorySystem (store / recall)
    knowledge   → KnowledgeManager.search (the previously unwired step)
    tools       → ToolManager (permissions/approval/verification stay inside)
    model       → ModelRouter (configured local brain)

and that tool verification is surfaced, failed capabilities degrade without
fabricating success, and every operation is recorded through the existing
ExecutionAudit (kind="capability").
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sage.audit.logger import ExecutionAudit
from sage.core.container import Container
from sage.knowledge.interfaces import KnowledgeManager
from sage.memory.interfaces import MemorySystem
from sage.memory.models import MemoryItem, MemoryType
from sage.models.interfaces import CompletionResponse, ModelRouter
from sage.orchestrator.engine import DefaultOrchestrator
from sage.orchestrator.models import IntentKind, PipelineStep
from sage.tools.interfaces import ToolManager, ToolResult

CANNED_REPLY = "Model says: hello."


# -- Duck-typed doubles (no engine boot required) -----------------------------


class RecordingLanguageModel:
    provider = "recording"
    model_name = "recording-v1"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: Any) -> CompletionResponse:
        self.calls += 1
        return CompletionResponse(
            content=CANNED_REPLY,
            model=self.model_name,
            provider=self.provider,
            usage={},
            raw={},
            finish_reason="stop",
        )


class FakeRouter:
    """ModelRouter double: hands out the recording LM (config-driven seam)."""

    def __init__(self) -> None:
        self.lm = RecordingLanguageModel()

    def get_language_model(self, *, capability: str | None = None) -> RecordingLanguageModel:
        return self.lm

    def get_embedding_model(self) -> None:
        return None


class FakeMemorySystem:
    def __init__(self, recalled: list[MemoryItem] | None = None) -> None:
        self.stored: list[MemoryItem] = []
        self.recalled = list(recalled or [])
        self.recall_queries: list[str] = []

    async def store(self, item: MemoryItem) -> str:
        self.stored.append(item)
        return "mem_1"

    async def store_cognitive(self, item: MemoryItem) -> str:
        self.stored.append(item)
        return "mem_1"

    async def recall(self, query: str, *, limit: int = 10, types: Any = None) -> list[MemoryItem]:
        self.recall_queries.append(query)
        return self.recalled[:limit]


class FakeKnowledgeManager:
    def __init__(self, hits: list[SimpleNamespace] | None = None) -> None:
        self.hits = list(hits or [])
        self.searches: list[str] = []

    async def search(self, query: str, *, limit: int = 10) -> list[SimpleNamespace]:
        self.searches.append(query)
        return self.hits[:limit]


class FakeToolManager:
    def __init__(
        self,
        result: ToolResult | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._result = result
        self._exc = exc
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def register(self, tool: Any) -> None:  # pragma: no cover - must not be called
        raise AssertionError("orchestrator must never register tools itself")

    def list_tools(self) -> list[Any]:  # pragma: no cover - must not be called
        return []

    async def invoke(self, name: str, **params: Any) -> ToolResult:
        self.calls.append((name, params))
        if self._exc is not None:
            raise self._exc
        assert self._result is not None
        return self._result


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def record(self, **fields: Any) -> SimpleNamespace:
        self.records.append(fields)
        return SimpleNamespace(**fields)


def build(registrations: dict[Any, Any]) -> DefaultOrchestrator:
    """Bare container + orchestrator; only the given Protocol keys are wired."""
    container = Container()
    for key, value in registrations.items():
        if value is not None:
            container.register_instance(key, value)
    return DefaultOrchestrator(container)


# -- 1. Model-only requests ---------------------------------------------------


async def test_model_only_request_routes_to_model() -> None:
    router = FakeRouter()
    orch = build({ModelRouter: router})

    result = await orch.handle("What is RAG?")

    assert result.intent.kind == IntentKind.CHAT
    assert [s.step for s in result.steps] == [
        PipelineStep.ANALYZE_INTENT,
        PipelineStep.RETRIEVE,
        PipelineStep.COMPOSE_RESPONSE,
    ]
    assert router.lm.calls == 1
    assert result.response == CANNED_REPLY


# -- 2. Memory requests -------------------------------------------------------


async def test_remember_request_routes_to_memory() -> None:
    mem = FakeMemorySystem()
    orch = build({MemorySystem: mem})

    result = await orch.handle(
        "Remember that SAGE should remain simple and user-controlled."
    )

    assert result.intent.kind == IntentKind.REMEMBER
    assert len(mem.stored) == 1
    assert "SAGE should remain simple and user-controlled" in mem.stored[0].content
    assert any(s.step == PipelineStep.STORE_MEMORY and s.success for s in result.steps)
    assert "remember" in result.response.lower()


async def test_recall_request_routes_to_memory() -> None:
    item = MemoryItem(
        type=MemoryType.LONG_TERM,
        content="SAGE is user-controlled.",
        importance=0.5,
        confidence=0.9,
    )
    mem = FakeMemorySystem(recalled=[item])
    orch = build({MemorySystem: mem})

    result = await orch.handle("what do you remember about user control")

    assert result.intent.kind == IntentKind.RECALL
    assert mem.recall_queries, "memory recall must be consulted"
    assert "SAGE is user-controlled." in result.response


async def test_what_did_i_ask_you_to_remember_lists_memories() -> None:
    item = MemoryItem(
        type=MemoryType.LONG_TERM,
        content="Keep SAGE simple.",
        importance=0.5,
        confidence=0.9,
    )
    mem = FakeMemorySystem(recalled=[item])
    orch = build({MemorySystem: mem})

    result = await orch.handle("What did I ask you to remember?")

    assert result.intent.kind == IntentKind.RECALL
    assert "Keep SAGE simple." in result.response


# -- 3. Knowledge / retrieval requests (previously unwired step) --------------


async def test_knowledge_search_request_routes_to_knowledge_manager() -> None:
    hit = SimpleNamespace(
        title="Tomato irrigation guide",
        snippet="Water tomatoes deeply twice weekly.",
        document_id="doc_1",
    )
    km = FakeKnowledgeManager([hit])
    orch = build({KnowledgeManager: km})

    result = await orch.handle("Search the knowledge I have stored about tomato irrigation.")

    assert result.intent.kind == IntentKind.KNOWLEDGE
    assert [s.step for s in result.steps] == [
        PipelineStep.ANALYZE_INTENT,
        PipelineStep.SEARCH_KNOWLEDGE,
        PipelineStep.COMPOSE_RESPONSE,
    ]
    assert km.searches == ["tomato irrigation"]
    assert "Tomato irrigation guide" in result.response
    assert "Water tomatoes deeply twice weekly." in result.response


async def test_knowledge_information_question_routes_to_knowledge_manager() -> None:
    hit = SimpleNamespace(
        title="Irrigation notes",
        snippet="Morning watering reduces evaporation.",
        document_id="doc_2",
    )
    km = FakeKnowledgeManager([hit])
    orch = build({KnowledgeManager: km})

    result = await orch.handle("What information do we have about irrigation?")

    assert result.intent.kind == IntentKind.KNOWLEDGE
    assert km.searches == ["irrigation"]
    assert "Irrigation notes" in result.response


async def test_knowledge_intent_is_not_hijacked_by_domain_routing() -> None:
    """'tomatoes' is an agriculture keyword, but an explicit knowledge lookup
    must stay a knowledge lookup."""
    km = FakeKnowledgeManager([])
    orch = build({KnowledgeManager: km})

    result = await orch.handle("Search the knowledge I have stored about tomatoes.")

    assert result.intent.kind == IntentKind.KNOWLEDGE
    assert result.response == "I don't have matching knowledge yet."


async def test_recall_priority_unchanged_for_memory_phrasing() -> None:
    """'what do you know about X' stays RECALL (memory), not KNOWLEDGE."""
    orch = build({MemorySystem: FakeMemorySystem(), KnowledgeManager: FakeKnowledgeManager()})

    result = await orch.handle("what do you know about tomatoes")

    assert result.intent.kind == IntentKind.RECALL


# -- 4/5. Tools + existing verification ---------------------------------------


async def test_tool_request_routes_through_tool_manager() -> None:
    manager = FakeToolManager(
        ToolResult(success=True, output={"topic": "t", "summary": "s"}, metadata={})
    )
    orch = build({ToolManager: manager})

    result = await orch.handle("Learn about t")

    assert result.intent.kind == IntentKind.TOOL
    assert manager.calls == [("web_learn", {"topic": "t"})]
    assert "s" in result.response


async def test_tool_output_verification_is_surfaced() -> None:
    verified = FakeToolManager(
        ToolResult(
            success=True,
            output={"topic": "t", "summary": "s"},
            metadata={"verification": {"verified": True, "confidence": 1.0, "issue_count": 0}},
        )
    )
    orch = build({ToolManager: verified})
    result = await orch.handle("Learn about t")
    assert "Verification: verified" in result.response

    flagged = FakeToolManager(
        ToolResult(
            success=True,
            output={"topic": "t", "summary": "s"},
            metadata={"verification": {"verified": False, "confidence": 0.6, "issue_count": 2}},
        )
    )
    orch2 = build({ToolManager: flagged})
    result2 = await orch2.handle("Learn about t")
    assert "Verification: flagged" in result2.response
    assert "issues: 2" in result2.response


# -- 6. Failed capabilities degrade without fabricating success ---------------


async def test_failed_tool_degrades_without_fabricated_success() -> None:
    manager = FakeToolManager(ToolResult(success=False, error="no usable search results"))
    orch = build({ToolManager: manager})

    result = await orch.handle("Learn about impossible topic")

    assert result.intent.kind == IntentKind.TOOL
    assert "couldn't complete" in result.response
    assert "no usable search results" in result.response
    assert "Verification: verified" not in result.response


async def test_knowledge_miss_reports_honestly() -> None:
    orch = build({KnowledgeManager: FakeKnowledgeManager([])})

    result = await orch.handle("What information do we have about cold fusion?")

    assert result.intent.kind == IntentKind.KNOWLEDGE
    assert result.response == "I don't have matching knowledge yet."


async def test_missing_subsystems_are_controlled() -> None:
    """No memory/knowledge/tools at all → controlled messages, no crash."""
    orch = build({ModelRouter: FakeRouter()})

    remember = await orch.handle("remember: x")
    assert remember.response  # store degrades but answers

    learn = await orch.handle("Learn about x")
    assert "tool framework is unavailable" in learn.response.lower()


# -- 7. Existing audit/logging path -------------------------------------------


async def test_capability_operation_is_audited() -> None:
    audit = FakeAudit()
    mem = FakeMemorySystem()
    orch = build({MemorySystem: mem, ExecutionAudit: audit})

    result = await orch.handle("Remember that SAGE stays simple")

    assert result.intent.kind == IntentKind.REMEMBER
    assert len(audit.records) == 1
    rec = audit.records[0]
    assert rec["kind"] == "capability"
    assert rec["status"] == "ok"
    assert rec["subject_id"] == result.plan_id
    assert rec["detail"]["capability"] == "remember"
    assert any(s["step"] == "store_memory" and s["ok"] for s in rec["detail"]["steps"])
    assert rec["detail"]["request_preview"].startswith("Remember that SAGE stays simple")


async def test_tool_operation_audits_verification_and_failures() -> None:
    audit = FakeAudit()

    ok_manager = FakeToolManager(
        ToolResult(
            success=True,
            output={"summary": "done"},
            metadata={"verification": {"verified": True, "confidence": 1.0, "issue_count": 0}},
        )
    )
    orch = build({ToolManager: ok_manager, ExecutionAudit: audit})
    await orch.handle("Learn about t")
    rec = audit.records[-1]
    assert rec["kind"] == "capability"
    assert rec["status"] == "ok"
    assert rec["detail"]["tool"] == "web_learn"
    assert rec["detail"]["verification"] == {
        "verified": True,
        "confidence": 1.0,
        "issue_count": 0,
    }

    bad_manager = FakeToolManager(ToolResult(success=False, error="search failed"))
    orch2 = build({ToolManager: bad_manager, ExecutionAudit: audit})
    await orch2.handle("Learn about t")
    rec2 = audit.records[-1]
    assert rec2["status"] == "error"
    assert rec2["detail"]["tool_error"] == "search failed"
    assert "verification" not in rec2["detail"]


async def test_audit_absence_never_breaks_the_loop() -> None:
    """No ExecutionAudit in the container → requests still answer."""
    orch = build({MemorySystem: FakeMemorySystem()})

    result = await orch.handle("remember: audit optional")

    assert result.intent.kind == IntentKind.REMEMBER
    assert result.response