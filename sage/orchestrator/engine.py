"""
Cognitive Orchestrator.

User → Conversation → Orchestrator → (Intent → Plan → Memory/Knowledge/
Reasoning/Planning/Agents/Tools) → Response
"""

from __future__ import annotations

import contextlib
import re
import time
from typing import Any

from sage.core.container import Container
from sage.logging import get_logger
from sage.orchestrator.intent import IntentAnalyzer
from sage.orchestrator.models import (
    ExecutionPlan,
    Intent,
    IntentKind,
    OrchestratorResult,
    PipelineStep,
    StepResult,
)
from sage.utils.ids import new_id

log = get_logger(__name__)

#: Relevance at which a new explicit user statement REPLACES an existing
#: user-stated memory instead of appending a near-duplicate (versioned update;
#: history preserved). Deliberately NOT the Lean adapter's 0.60 short-circuit
#: threshold — different purpose, different calibration.
_MEMORY_REPLACE_RELEVANCE = 0.5


class DefaultOrchestrator:
    def __init__(self, container: Any) -> None:
        self._container: Container = container
        self._analyzer = IntentAnalyzer()

    async def analyze_intent(
        self, message: str, *, context: dict[str, Any] | None = None
    ) -> Intent:
        return self._analyzer.analyze(message, context=context)

    def _build_plan(self, intent: Intent) -> ExecutionPlan:
        steps: list[PipelineStep] = [PipelineStep.ANALYZE_INTENT]

        if intent.kind == IntentKind.STATUS:
            # Status is already a complete user-facing response
            steps.append(PipelineStep.STATUS)
            return ExecutionPlan(intent=intent, steps=steps)

        if intent.kind == IntentKind.REMEMBER:
            steps.append(PipelineStep.STORE_MEMORY)
            steps.append(PipelineStep.LEARN)
            steps.append(PipelineStep.COMPOSE_RESPONSE)
            return ExecutionPlan(intent=intent, steps=steps)

        if intent.kind == IntentKind.RECALL:
            steps.append(PipelineStep.RETRIEVE)
            steps.append(PipelineStep.RECALL_MEMORY)
            steps.append(PipelineStep.COMPOSE_RESPONSE)
            return ExecutionPlan(intent=intent, steps=steps)

        if intent.kind == IntentKind.KNOWLEDGE:
            # Explicit knowledge-base query → search the existing knowledge
            # manager and compose from its hits (no second RAG pipeline).
            steps.append(PipelineStep.SEARCH_KNOWLEDGE)
            steps.append(PipelineStep.COMPOSE_RESPONSE)
            return ExecutionPlan(intent=intent, steps=steps)

        if intent.kind == IntentKind.PLAN:
            steps.extend(
                [
                    PipelineStep.RETRIEVE,
                    PipelineStep.PLAN,
                    PipelineStep.COMPOSE_RESPONSE,
                ]
            )
            return ExecutionPlan(intent=intent, steps=steps)

        if intent.kind == IntentKind.REASON:
            steps.extend(
                [
                    PipelineStep.RETRIEVE,
                    PipelineStep.REASON,
                    PipelineStep.COMPOSE_RESPONSE,
                ]
            )
            return ExecutionPlan(intent=intent, steps=steps)

        if intent.kind in {IntentKind.RESEARCH, IntentKind.DOCUMENT, IntentKind.AGENT}:
            steps.extend(
                [
                    PipelineStep.RETRIEVE,
                    PipelineStep.DISPATCH_AGENT,
                    PipelineStep.COMPOSE_RESPONSE,
                ]
            )
            return ExecutionPlan(intent=intent, steps=steps)

        if intent.kind == IntentKind.LEARN:
            steps.extend(
                [
                    PipelineStep.LEARN,
                    PipelineStep.STORE_MEMORY,
                    PipelineStep.COMPOSE_RESPONSE,
                ]
            )
            return ExecutionPlan(intent=intent, steps=steps)

        if intent.kind == IntentKind.TOOL:
            # Explicit tool imperative → invoke through the standard ToolManager,
            # then compose the user-facing response from the tool artifact.
            steps.append(PipelineStep.INVOKE_TOOL)
            steps.append(PipelineStep.COMPOSE_RESPONSE)
            return ExecutionPlan(intent=intent, steps=steps)

        # Default chat path — layered retrieval then compose
        steps.extend(
            [
                PipelineStep.RETRIEVE,
                PipelineStep.COMPOSE_RESPONSE,
            ]
        )
        return ExecutionPlan(intent=intent, steps=steps)

    async def _select_tool_intent(
        self, intent: Intent, message: str, ctx: dict[str, Any]
    ) -> Intent:
        """Ask the configured model which registered tool applies, if any.

        Returns the intent unchanged unless a *registered* tool was chosen and
        its required arguments were supplied; tool execution itself still goes
        through :class:`~sage.tools.interfaces.ToolManager`.
        """
        from sage.models.interfaces import ModelRouter
        from sage.tools.interfaces import ToolManager
        from sage.tools.selection import ModelToolSelector

        router = self._container.try_resolve(ModelRouter)
        tools = self._container.try_resolve(ToolManager)
        if router is None or tools is None:
            return intent

        decision = await ModelToolSelector(router, tools).decide(message)
        if decision is None:
            return intent

        name, arguments = decision
        if not ModelToolSelector.has_required_arguments(tools, name, arguments):
            log.debug("tools.selection_missing_arguments", tool=name)
            return intent

        log.info("tools.auto_selected", tool=name)
        ctx["tool_selection"] = {"tool": name, "arguments": arguments}
        first_value = next(iter(arguments.values()), message)
        return intent.model_copy(
            update={
                "kind": IntentKind.TOOL,
                "subject": str(first_value),
                "entities": {
                    **intent.entities,
                    "tool": name,
                    "args": arguments,
                    "auto_selected": True,
                },
                "confidence": min(intent.confidence, 0.8),
            }
        )

    async def handle(
        self,
        message: str,
        *,
        session_id: str | None = None,
        user_id: str = "default",
        context: dict[str, Any] | None = None,
    ) -> OrchestratorResult:
        ctx = dict(context or {})
        ctx.setdefault("session_id", session_id)
        ctx.setdefault("user_id", user_id)
        ctx.setdefault("history", [])
        ctx.setdefault("memories", [])
        ctx.setdefault("knowledge", [])
        ctx.setdefault("preferences", {})

        # Fuse cognitive context when available (v0.5.0)
        await self._merge_unified_context(ctx, message)

        intent = await self.analyze_intent(message, context=ctx)
        # Proactive suggestions intent
        if intent.kind.value == "chat" and self._is_suggestions_query(message):
            return await self._handle_suggestions(message, ctx, session_id, user_id)

        # Conversational understanding — deterministic and cheap (no extra LLM
        # call): dialogue mode + response policy around the capability route.
        from sage.conversation.understanding import ConversationMode, social_response, understand

        und = understand(message)
        ctx["conversation"] = und
        # Deterministic natural social replies for greeting/goodbye-only turns:
        # no retrieval, no tools, no model call — SAGE responds as a partner.
        social_text = None
        if intent.kind in {IntentKind.CHAT, IntentKind.UNKNOWN} and und.is_social:
            social_text = social_response(message, und)
            ctx["social_response"] = social_text

        # Model-assisted tool selection. The configured local brain is not
        # tool-capable, so the decision is a schema-constrained JSON request
        # (see sage.tools.selection) rather than a native ``tools`` payload.
        # Consulted only for ``tool_request`` turns where no explicit imperative
        # matched; a selection simply reuses the standard TOOL plan, so
        # permissions, approval, verification and audit are the existing ones.
        if (
            social_text is None
            and intent.kind == IntentKind.CHAT
            and und.mode == ConversationMode.TOOL_REQUEST
        ):
            intent = await self._select_tool_intent(intent, message, ctx)

        plan = self._build_plan(intent)
        if social_text is not None:
            plan = ExecutionPlan(
                intent=intent,
                steps=[PipelineStep.ANALYZE_INTENT, PipelineStep.COMPOSE_RESPONSE],
            )
        step_results: list[StepResult] = []
        response_parts: list[str] = []

        log.info(
            "orchestrator.handle",
            intent=intent.kind.value,
            confidence=intent.confidence,
            steps=[s.value for s in plan.steps],
            plan_id=plan.id,
        )

        for step in plan.steps:
            t0 = time.perf_counter()
            try:
                out = await self._run_step(step, intent, message, ctx)
                duration = (time.perf_counter() - t0) * 1000
                step_results.append(
                    StepResult(step=step, success=True, output=out, duration_ms=duration)
                )
                if step == PipelineStep.COMPOSE_RESPONSE and isinstance(out, str):
                    response_parts.append(out)
                elif step == PipelineStep.STATUS and isinstance(out, str):
                    response_parts.append(out)
                elif (
                    step
                    in {
                        PipelineStep.STORE_MEMORY,
                        PipelineStep.RECALL_MEMORY,
                        PipelineStep.SEARCH_KNOWLEDGE,
                        PipelineStep.PLAN,
                        PipelineStep.REASON,
                        PipelineStep.DISPATCH_AGENT,
                        PipelineStep.LEARN,
                        PipelineStep.INVOKE_TOOL,
                    }
                    and isinstance(out, str)
                    and not out.startswith(("recalled=", "knowledge=", "learning="))
                ):
                    # User-facing intermediate outputs; compose will prefer these
                    ctx.setdefault("_artifacts", []).append(out)
            except Exception as exc:
                duration = (time.perf_counter() - t0) * 1000
                log.exception("orchestrator.step_failed", step=step.value)
                step_results.append(
                    StepResult(
                        step=step,
                        success=False,
                        error=str(exc),
                        duration_ms=duration,
                    )
                )

        if not response_parts:
            artifacts = ctx.get("_artifacts") or []
            if artifacts:
                response_parts.append(str(artifacts[-1]))
            else:
                response_parts.append("I processed your request but produced no response.")

        result = OrchestratorResult(
            plan_id=plan.id,
            intent=intent,
            response="\n".join(response_parts).strip(),
            steps=step_results,
            metadata={
                "session_id": session_id,
                "user_id": user_id,
                "step_count": len(step_results),
                "failed_steps": [s.step.value for s in step_results if not s.success],
                "conversation": {
                    "mode": und.mode.value,
                    "tone": und.policy.tone,
                    "length": und.policy.length,
                    "response_type": "social" if social_text is not None else "model",
                    "topic": (
                        intent.subject[:120]
                        if intent.kind not in {IntentKind.CHAT, IntentKind.UNKNOWN}
                        else None
                    ),
                },
            },
        )
        await self._audit_capability(result, message, ctx)
        return result

    async def _audit_capability(
        self,
        result: OrchestratorResult,
        message: str,
        ctx: dict[str, Any],
    ) -> None:
        """Record the capability decision through the existing execution audit.

        One record per request answers: what was requested (truncated preview;
        the full text already lives in conversation turns), which capability
        was selected, which pipeline steps executed, whether tool verification
        ran, and whether the operation succeeded. Best-effort: a missing or
        failing audit system never breaks the response loop.
        """
        from sage.audit.logger import ExecutionAudit

        audit = self._container.try_resolve(ExecutionAudit)
        if audit is None:
            return

        tool_result = ctx.get("tool_result")
        verification = (
            getattr(tool_result, "metadata", {}).get("verification")
            if tool_result is not None
            else None
        )
        failed_steps = [s.step.value for s in result.steps if not s.success]
        tool_error = None
        if tool_result is not None and not getattr(tool_result, "success", True):
            tool_error = getattr(tool_result, "error", None)

        detail: dict[str, Any] = {
            "capability": result.intent.kind.value,
            "intent_confidence": result.intent.confidence,
            "request_chars": len(message),
            "request_preview": message[:120],
            "steps": [
                {"step": s.step.value, "ok": s.success, "ms": round(s.duration_ms, 1)}
                for s in result.steps
            ],
            "failed_steps": failed_steps,
        }
        und = ctx.get("conversation")
        if und is not None:
            detail["conversation_mode"] = und.mode.value
        if result.intent.kind == IntentKind.TOOL:
            detail["tool"] = result.intent.entities.get("tool")
        if isinstance(verification, dict):
            detail["verification"] = {
                "verified": bool(verification.get("verified")),
                "confidence": verification.get("confidence"),
                "issue_count": verification.get("issue_count"),
            }
        if tool_error:
            detail["tool_error"] = tool_error

        with contextlib.suppress(Exception):
            await audit.record(
                kind="capability",
                subject_id=result.plan_id,
                principal=str(result.metadata.get("user_id") or "default"),
                status="error" if (failed_steps or tool_error) else "ok",
                summary=f"{result.intent.kind.value}: {message[:80]}",
                duration_ms=round(sum(s.duration_ms for s in result.steps), 1),
                detail=detail,
            )

    async def _run_step(
        self,
        step: PipelineStep,
        intent: Intent,
        message: str,
        ctx: dict[str, Any],
    ) -> Any:
        if step == PipelineStep.ANALYZE_INTENT:
            return intent.model_dump()

        if step == PipelineStep.RETRIEVE:
            return await self._step_retrieve(intent, message, ctx)

        if step == PipelineStep.RECALL_MEMORY:
            return await self._step_recall(intent, message, ctx)

        if step == PipelineStep.SEARCH_KNOWLEDGE:
            return await self._step_knowledge(intent, message, ctx)

        if step == PipelineStep.STORE_MEMORY:
            return await self._step_store(intent, ctx)

        if step == PipelineStep.REASON:
            return await self._step_reason(intent, ctx)

        if step == PipelineStep.PLAN:
            return await self._step_plan(intent, ctx)

        if step == PipelineStep.DISPATCH_AGENT:
            return await self._step_agent(intent, message, ctx)

        if step == PipelineStep.LEARN:
            return await self._step_learn(intent, ctx)

        if step == PipelineStep.STATUS:
            return await self._step_status()

        if step == PipelineStep.COMPOSE_RESPONSE:
            return await self._step_compose(intent, message, ctx)

        if step == PipelineStep.INVOKE_TOOL:
            return await self._step_invoke_tool(intent, ctx)

        return None

    async def _step_invoke_tool(self, intent: Intent, ctx: dict[str, Any]) -> str:
        """Run an explicit tool request through the standard ToolManager.

        The manager is resolved from the container (dependency injection — the
        orchestrator never constructs tools or model clients itself). Any tool
        failure is converted into a controlled user-facing message: a failed
        tool must degrade the response, never crash the loop.
        """
        from sage.tools.interfaces import ToolManager

        manager = self._container.try_resolve(ToolManager)
        if manager is None:
            return "The tool framework is unavailable in this runtime."

        tool_name = str(intent.entities.get("tool") or "").strip()
        if not tool_name:
            return "No tool was specified for this request."

        args = intent.entities.get("args")
        if not isinstance(args, dict):
            args = {}

        result = await manager.invoke(tool_name, **args)
        ctx["tool_result"] = result

        if result.success:
            return self._format_tool_output(tool_name, result)

        # Controlled degraded response — surface the reason, keep the loop alive.
        error = (result.error or "unknown error").strip()
        return f"I couldn't complete that with the {tool_name} tool: {error}"

    @staticmethod
    def _format_tool_output(tool_name: str, result: Any) -> str:
        """Render a successful ToolResult as a user-facing artifact."""
        output = getattr(result, "output", None)
        if isinstance(output, dict):
            summary = output.get("summary")
            if summary:
                lines = [str(summary)]
                sources = output.get("sources")
                if sources:
                    lines.append("Sources: " + ", ".join(str(s) for s in sources))
                text = "\n".join(lines)
            else:
                text = "\n".join(f"{key}: {value}" for key, value in output.items())
        elif output is None:
            text = f"{tool_name} completed."
        else:
            text = str(output)
        # Surface the existing Tool-R0 verification verdict (stamped by the
        # ToolManager) instead of leaving it hidden in result metadata.
        verification = getattr(result, "metadata", {}).get("verification")
        if isinstance(verification, dict):
            verdict = "verified" if verification.get("verified") else "flagged"
            text = (
                f"{text}\nVerification: {verdict} "
                f"(confidence {verification.get('confidence')}, "
                f"issues: {verification.get('issue_count')})"
            )
        return text

    async def _step_recall(self, intent: Intent, message: str, ctx: dict[str, Any]) -> str | None:
        from sage.memory.interfaces import MemorySystem

        mem = self._container.try_resolve(MemorySystem)
        if not mem:
            return None
        query = intent.subject if intent.kind == IntentKind.RECALL else message
        query = self._clean_recall_query(query)
        items = await mem.recall(query, limit=10 if intent.kind == IntentKind.RECALL else 5)
        ctx["memories"] = [m.content for m in items]
        ctx["memory_items"] = items
        if intent.kind == IntentKind.RECALL:
            if not items:
                return "I don't have matching memories yet."
            lines = ["Here is what I remember:"]
            for i, item in enumerate(items, 1):
                lines.append(
                    f"{i}. [{item.type.value} · importance {item.importance:.2f}"
                    f" · conf {item.confidence:.2f}] {item.content}"
                )
            return "\n".join(lines)
        return f"recalled={len(items)}"

    def _clean_recall_query(self, query: str) -> str:
        q = re.sub(
            r"^(what do you (know|remember)"
            r"|what did i (?:ask|tell) you(?: to)? remember"
            r"|recall|show memories)\s*",
            "",
            query,
            flags=re.I,
        ).strip()
        q = re.sub(r"^about\s+", "", q, flags=re.I).strip()
        stop = {"a", "an", "the", "my", "me", "about", "regarding", "on", "for", "of"}
        tokens = [t for t in re.split(r"\W+", q) if t and t.lower() not in stop]
        # Empty result (e.g. "What did I ask you to remember?") → "" which the
        # real MemorySystem resolves to recent memories via list_recent.
        return " ".join(tokens) if tokens else ""

    async def _step_knowledge(self, intent: Intent, message: str, ctx: dict[str, Any]) -> str:
        from sage.knowledge.interfaces import KnowledgeManager

        km = self._container.try_resolve(KnowledgeManager)
        if not km:
            if intent.kind == IntentKind.KNOWLEDGE:
                return "The knowledge system is unavailable right now."
            return "knowledge=0"
        query = (intent.subject or message).rstrip(" ?.!")
        hits = await km.search(query, limit=3)
        ctx["knowledge"] = [f"{h.title}: {h.snippet}" for h in hits if h.snippet]
        if intent.kind == IntentKind.KNOWLEDGE:
            # Explicit knowledge query → deterministic listing of what SAGE
            # has stored (same style as recall); the model must not invent it.
            if not hits:
                return "I don't have matching knowledge yet."
            lines = ["Here is what I have in my knowledge base:"]
            for i, hit in enumerate(hits, 1):
                title = (hit.title or "").strip()
                snippet = (hit.snippet or "").strip()
                if title and snippet:
                    lines.append(f"{i}. {title} — {snippet}")
                else:
                    lines.append(f"{i}. {title or snippet}")
            return "\n".join(lines)
        return f"knowledge={len(hits)}"

    async def _step_store(self, intent: Intent, ctx: dict[str, Any]) -> str:
        from sage.memory.interfaces import MemorySystem
        from sage.memory.models import MemoryItem, MemoryStatus, MemoryType

        mem = self._container.try_resolve(MemorySystem)
        if not mem:
            return "Memory system is unavailable."
        fact = intent.subject.strip()
        if not fact:
            return "Nothing to remember."
        # Secrets/credentials never enter long-term memory (transparent refusal).
        if re.search(
            r"\b(?:password|passphrase|api[_-]?key|apikey|secret|token|credential)s?\b\s*"
            r"(?:[:=]|\bis\b|\bwas\b)",
            fact,
            re.I,
        ):
            return (
                "I won't store that in long-term memory — it looks like a secret or "
                "credential. Keep those out of durable memory; rephrase if you meant "
                "something non-sensitive."
            )
        # Memory lifecycle — REPLACE before ADD: a rephrased or changed user
        # statement updates the existing user-stated memory (versioned; history
        # preserved) instead of blindly appending a near-duplicate.
        mid: str | None = None
        replaced = False
        exact_duplicate = False
        scored = getattr(mem, "recall_scored", None)
        update_fn = getattr(mem, "update", None)
        if callable(scored) and callable(update_fn):
            try:
                pairs = await scored(fact, limit=5)
            except Exception:
                log.exception("orchestrator.memory_replace_probe_failed")
                pairs = []
            for existing, rel in pairs:
                replaceable = existing.source == "user" or "user_stated" in existing.tags
                same = existing.content.strip().lower() == fact.lower()
                if same and replaceable:
                    exact_duplicate = True  # store() reinforces instead
                    break
                if replaceable and rel >= _MEMORY_REPLACE_RELEVANCE:
                    await update_fn(
                        existing.id,
                        content=fact,
                        metadata={
                            **existing.metadata,
                            "status": MemoryStatus.CURRENT.value,
                            "supersedes": existing.content[:160],
                        },
                    )
                    mid, replaced = existing.id, True
                    break
        if exact_duplicate:
            return (
                "Understood — that matches what I already remember, so I reinforced "
                "it instead of storing a duplicate."
            )
        if mid is None:
            # Use cognitive store path if available
            store_fn = getattr(mem, "store_cognitive", None)
            item = MemoryItem(
                type=MemoryType.LONG_TERM,
                content=fact,
                importance=0.75,
                confidence=0.9,
                source="user",
                tags=["user_stated"],
                metadata={"status": MemoryStatus.CURRENT.value},
            )
            mid = await store_fn(item) if callable(store_fn) else await mem.store(item)
        ctx["stored_memory_id"] = mid
        # Extract entities/relations into knowledge graph
        from sage.knowledge.graph.interfaces import KnowledgeGraph

        kg = self._container.try_resolve(KnowledgeGraph)
        if kg:
            try:
                await kg.extract_and_merge(
                    fact, source="user_memory", source_ref=mid, memory_id=mid
                )
            except Exception:
                log.exception("orchestrator.graph_from_memory_failed")
        if replaced:
            return (
                "Updated my memory: «" + fact + "» — the earlier similar memory was "
                "replaced; its previous versions are kept in history."
            )
        return f"Understood. I will remember that (id: {mid}).\n«{fact}»"

    async def _step_retrieve(self, intent: Intent, message: str, ctx: dict[str, Any]) -> str:
        from sage.retrieval.interfaces import Retriever

        retriever = self._container.try_resolve(Retriever)
        query = intent.subject or message
        if not retriever:
            # Fallback to separate memory + knowledge
            await self._step_recall(intent, message, ctx)
            await self._step_knowledge(intent, message, ctx)
            return "retrieve=fallback"
        result = await retriever.retrieve(query, limit=10)
        ctx["memories"] = list(result.memories)
        ctx["graph_facts"] = list(result.graph_facts)
        ctx["documents"] = list(result.documents)
        ctx["knowledge"] = list(result.documents) + list(result.graph_facts)
        ctx["retrieval"] = result
        ctx["retrieval_confidence"] = result.overall_confidence
        return (
            f"retrieve=ok memories={len(result.memories)} "
            f"graph={len(result.graph_facts)} docs={len(result.documents)} "
            f"conf={result.overall_confidence:.2f}"
        )

    async def _step_reason(self, intent: Intent, ctx: dict[str, Any]) -> str:
        from sage.reasoning.interfaces import ReasoningEngine
        from sage.reasoning.models import ReasoningContext

        engine = self._container.try_resolve(ReasoningEngine)
        if not engine:
            return "Reasoning engine is unavailable."
        result = await engine.reason(
            intent.subject or intent.raw_message,
            context=ReasoningContext(
                memories=list(ctx.get("memories") or []),
                knowledge=list(ctx.get("knowledge") or []),
                graph_facts=list(ctx.get("graph_facts") or []),
                documents=list(ctx.get("documents") or []),
                metadata={
                    "retrieval_explanation": getattr(
                        ctx.get("retrieval"), "explanation", None
                    )
                    or [],
                    "retrieval_confidence": ctx.get("retrieval_confidence"),
                },
            ),
            use_retrieval=False,  # already retrieved
        )
        # Prefer full explainability report when present
        if result.explainability is not None:
            return result.explainability.format()
        lines = [
            f"Strategy: {result.strategy.value}",
            f"Confidence: {result.confidence:.2f}",
            "",
            "Trace:",
        ]
        for step in result.trace:
            lines.append(f"  {step.index}. ({step.kind}) {step.thought}")
        lines += ["", f"Conclusion: {result.conclusion}"]
        if result.alternatives:
            lines.append("Alternatives:")
            for alt in result.alternatives:
                lines.append(f"  - {alt}")
        if result.risks:
            lines.append("Risks:")
            for risk in result.risks:
                lines.append(f"  - {risk}")
        return "\n".join(lines)

    async def _step_plan(self, intent: Intent, ctx: dict[str, Any]) -> str:
        from sage.agents.interfaces import AgentOrchestrator, AgentTask

        orch = self._container.try_resolve(AgentOrchestrator)
        goal_text = intent.subject or intent.raw_message
        if orch:
            result = await orch.dispatch(
                AgentTask(description=goal_text, domain="planning", priority=0.7)
            )
            return result.output if result.success else (result.error or "Planning failed.")

        from sage.planning.interfaces import PlanningEngine

        engine = self._container.try_resolve(PlanningEngine)
        if not engine:
            return "Planning engine is unavailable."
        goal = await engine.create_goal(goal_text)
        plan = await engine.plan(goal.id)
        lines = [f"Goal: {goal.description}", f"Plan: {plan.title}", "Steps:"]
        for step in plan.steps:
            lines.append(f"  {step.index + 1}. {step.title} — {step.detail}")
        return "\n".join(lines)

    async def _step_agent(self, intent: Intent, message: str, ctx: dict[str, Any]) -> str:
        from sage.agents.interfaces import AgentOrchestrator, AgentTask

        orch = self._container.try_resolve(AgentOrchestrator)
        if not orch:
            return "Agent framework is unavailable."
        domain = intent.entities.get("domain")
        if intent.kind == IntentKind.RESEARCH:
            domain = domain or "research"
        if intent.kind == IntentKind.DOCUMENT:
            domain = domain or "documents"
        result = await orch.dispatch(
            AgentTask(description=intent.subject or message, domain=domain)
        )
        return result.output if result.success else (result.error or "Agent task failed.")

    async def _step_learn(self, intent: Intent, ctx: dict[str, Any]) -> str:
        from sage.learning.interfaces import LearningEngine
        from sage.learning.models import Observation, ObservationKind

        learn = self._container.try_resolve(LearningEngine)
        if not learn:
            return "learning=skip"
        await learn.observe(
            Observation(
                kind=ObservationKind.CONVERSATION,
                content=intent.raw_message[:2000],
                metadata={"intent": intent.kind.value},
            )
        )
        # Simple preference parse: "I prefer X" / "prefer: key=value"
        m = re.search(r"prefer(?:ence)?\s*[:\s]+(.+)$", intent.raw_message, re.I)
        if m:
            body = m.group(1).strip()
            if "=" in body:
                k, _, v = body.partition("=")
                await learn.learn_preference(k.strip(), v.strip(), confidence=0.8, source="explicit")
                return f"Preference saved: {k.strip()}={v.strip()}"
            await learn.learn_preference("general", body, confidence=0.6, source="explicit")
            return f"Preference noted: {body}"
        return "learning=observed"

    async def _step_status(self) -> str:
        from sage.core.engine import SageEngine
        from sage.monitor.interfaces import HealthMonitor

        engine = self._container.try_resolve(SageEngine)
        monitor = self._container.try_resolve(HealthMonitor)
        lines: list[str] = []
        if engine:
            health = await engine.health()
            lines += [
                f"SAGE state: {engine.state.value}",
                f"Health: {health.level.value} — {health.message}",
                "Modules:",
            ]
            for m in health.modules:
                lines.append(f"  - {m.name}: {m.level.value} ({m.message})")
        if monitor:
            snap = await monitor.snapshot()
            lines.append("")
            lines.append(
                f"Resources: cpu={snap.get('cpu_percent')}% "
                f"mem={snap.get('memory_percent')}% "
                f"rss_mb={snap.get('rss_mb')}"
            )
        return "\n".join(lines) if lines else "Status unavailable."

    async def _try_skill(self, message: str, ctx: dict[str, Any]) -> str | None:
        """Run best matching shared skill for chat-like requests."""
        from sage.skills.interfaces import SkillLibrary

        lib = self._container.try_resolve(SkillLibrary)
        if not lib:
            return None
        skill_ctx = {
            "memories": list(ctx.get("memories") or []),
            "graph_facts": list(ctx.get("graph_facts") or []),
            "documents": list(ctx.get("documents") or []),
            "priorities": list(ctx.get("priorities") or []),
            "context_summary": ctx.get("context_summary") or "",
        }
        # Provide decision engine hook for decision skills
        from sage.decision.engine import DecisionEngine

        de = self._container.try_resolve(DecisionEngine)
        if de:

            async def _decide_fn(req: Any) -> Any:
                return await de.decide(req)

            skill_ctx["_decide_fn"] = _decide_fn

        result = await lib.invoke_best(
            message, context=skill_ctx, principal="core", min_score=0.30
        )
        if result is None or not result.success:
            return None
        return f"### SAGE Skill Library\n\n{result.format()}"

    async def _merge_unified_context(self, ctx: dict[str, Any], message: str) -> None:
        from sage.context.engine import CognitiveContextEngine

        cce = self._container.try_resolve(CognitiveContextEngine)
        if not cce:
            return
        try:
            unified = await cce.fuse()
            fused = unified.as_orchestrator_context()
            # Prefer fused memories/graph when retrieve hasn't filled them yet
            if not ctx.get("memories") and fused.get("memories"):
                ctx["memories"] = list(fused["memories"])
            if not ctx.get("graph_facts") and fused.get("graph_facts"):
                ctx["graph_facts"] = list(fused["graph_facts"])
            for key in (
                "context_summary",
                "active_projects",
                "priorities",
                "open_tasks",
                "long_term_interests",
                "suggestions",
                "environment",
                "pending_approvals_count",
                "running_workflows_count",
            ):
                if key in fused:
                    ctx[key] = fused[key]
            # Track interest from user message tokens
            for token in message.lower().replace(",", " ").split():
                if len(token) >= 5 and token.isalpha():
                    await cce.record_interest(token, weight=0.02)
                    break
        except Exception:
            log.exception("orchestrator.context_fuse_failed")

    def _is_suggestions_query(self, message: str) -> bool:
        lower = message.lower().strip()
        return any(
            p in lower
            for p in (
                "suggestions",
                "what should i focus",
                "what needs attention",
                "proactive",
                "remind me what",
                "session status",
                "context summary",
                "where did we leave",
            )
        )

    async def _handle_suggestions(
        self,
        message: str,
        ctx: dict[str, Any],
        session_id: str | None,
        user_id: str,
    ) -> OrchestratorResult:
        from sage.context.engine import CognitiveContextEngine
        from sage.orchestrator.models import Intent, IntentKind, OrchestratorResult

        cce = self._container.try_resolve(CognitiveContextEngine)
        lines = ["### Cognitive Context", ""]
        if cce:
            try:
                await cce.generate_suggestions()
                unified = await cce.fuse()
                lines.append(f"**Summary:** {unified.summary}")
                lines.append("")
                if unified.session.active_project_id:
                    lines.append(f"**Active project:** {unified.session.active_project_id}")
                if unified.priorities:
                    lines.append("**Priorities:**")
                    lines.extend(f"- {p}" for p in unified.priorities[:6])
                if unified.pending_approvals:
                    lines.append(f"\n**Pending approvals:** {len(unified.pending_approvals)}")
                if unified.running_workflows:
                    lines.append(f"**Open workflows:** {len(unified.running_workflows)}")
                lines.append("")
                lines.append("**Suggestions** (advisory only — nothing runs unless you approve):")
                sugg = await cce.suggestions(limit=8)
                if not sugg:
                    lines.append("- No open suggestions right now.")
                for s in sugg:
                    lines.append(f"- **{s.title}** ({s.category}, p={s.priority:.2f})")
                    lines.append(f"  {s.body}")
            except Exception as exc:
                lines.append(f"Context unavailable: {exc}")
        else:
            lines.append("Context engine not loaded.")

        text = "\n".join(lines)
        return OrchestratorResult(
            plan_id=new_id("xplan"),
            intent=Intent(
                kind=IntentKind.CHAT,
                confidence=0.9,
                subject=message,
                raw_message=message,
                hints=["context:suggestions"],
            ),
            response=text,
            steps=[],
            metadata={"session_id": session_id, "user_id": user_id, "mode": "context"},
        )

    async def _step_compose(self, intent: Intent, message: str, ctx: dict[str, Any]) -> str:
        # Deterministic social replies first — a greeting is a social
        # interaction, not a help request: acknowledge naturally and briefly,
        # without retrieving memory, invoking tools, or calling the model.
        social_text = ctx.get("social_response")
        if social_text is not None:
            return social_text
        # If earlier steps already produced a user-facing artifact for non-chat intents, use it
        artifacts = ctx.get("_artifacts") or []
        if intent.kind == IntentKind.TOOL and not artifacts:
            # The tool step raised or produced nothing: controlled fallback
            # instead of falling through to a generic chat answer.
            return "I processed your tool request but it did not produce a result."
        if intent.kind != IntentKind.CHAT and artifacts:
            return str(artifacts[-1])
        if intent.kind in {
            IntentKind.REMEMBER,
            IntentKind.RECALL,
            IntentKind.PLAN,
            IntentKind.REASON,
            IntentKind.STATUS,
            IntentKind.RESEARCH,
            IntentKind.DOCUMENT,
            IntentKind.AGENT,
            IntentKind.LEARN,
        } and artifacts:
            return str(artifacts[-1])

        # Shared Skill Library — prefer reusable skills over stub/chat model when matched
        if intent.kind == IntentKind.CHAT:
            skill_text = await self._try_skill(message, ctx)
            if skill_text:
                return skill_text

        from sage.config.settings import Settings
        from sage.conversation.personality import (
            build_system_prompt,
            memory_evidence_block,
            style_directive,
        )
        from sage.models.interfaces import CompletionRequest, Message, ModelRouter

        router = self._container.try_resolve(ModelRouter)
        if router is None:
            return f"I heard you, but no language model is configured. You said: «{message}»"

        und = ctx.get("conversation")
        style_text = (
            style_directive(
                und.policy.tone,
                length=und.policy.length,
                acknowledge_first=und.policy.acknowledge_first,
            )
            if und is not None
            else None
        )
        extra_bits: list[str] = []
        if ctx.get("context_summary"):
            extra_bits.append(f"Cognitive context: {ctx['context_summary']}")
        if ctx.get("priorities"):
            extra_bits.append("Priorities:\n- " + "\n- ".join(str(p) for p in ctx["priorities"][:5]))
        if ctx.get("active_projects"):
            extra_bits.append(
                "Active projects:\n- " + "\n- ".join(str(p) for p in ctx["active_projects"][:4])
            )
        if ctx.get("memories"):
            evidence = memory_evidence_block(list(ctx["memories"])[:5])
            if evidence:
                extra_bits.append(evidence)
        if ctx.get("graph_facts"):
            extra_bits.append(
                "Knowledge graph facts:\n- " + "\n- ".join(ctx["graph_facts"][:6])
            )
        if ctx.get("documents"):
            extra_bits.append("Documents:\n- " + "\n- ".join(ctx["documents"][:3]))
        elif ctx.get("knowledge"):
            extra_bits.append("Relevant knowledge:\n- " + "\n- ".join(ctx["knowledge"][:3]))
        if ctx.get("preferences"):
            extra_bits.append(f"User preferences: {ctx['preferences']}")

        system = build_system_prompt(
            extra="\n\n".join(extra_bits) if extra_bits else None, style=style_text
        )
        messages = [Message(role="system", content=system)]
        for role, content in ctx.get("history") or []:
            messages.append(Message(role=role, content=content))
        messages.append(Message(role="user", content=message))

        settings = self._container.try_resolve(Settings)
        lm = router.get_language_model()
        resp = await lm.complete(
            CompletionRequest(
                messages=messages,
                temperature=settings.models.temperature if settings else 0.7,
                max_tokens=settings.models.max_tokens if settings else 2048,
            )
        )
        return resp.content
