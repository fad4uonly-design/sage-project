"""
Cognitive Orchestrator.

User → Conversation → Orchestrator → (Intent → Plan → Memory/Knowledge/
Reasoning/Planning/Agents/Tools) → Response
"""

from __future__ import annotations

import re
import time
from typing import Any

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


class DefaultOrchestrator:
    def __init__(self, container: Any) -> None:
        self._container = container
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

        # Default chat path — layered retrieval then compose
        steps.extend(
            [
                PipelineStep.RETRIEVE,
                PipelineStep.COMPOSE_RESPONSE,
            ]
        )
        return ExecutionPlan(intent=intent, steps=steps)

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

        plan = self._build_plan(intent)
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
                        PipelineStep.PLAN,
                        PipelineStep.REASON,
                        PipelineStep.DISPATCH_AGENT,
                        PipelineStep.LEARN,
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

        return OrchestratorResult(
            plan_id=plan.id,
            intent=intent,
            response="\n".join(response_parts).strip(),
            steps=step_results,
            metadata={
                "session_id": session_id,
                "user_id": user_id,
                "step_count": len(step_results),
                "failed_steps": [s.step.value for s in step_results if not s.success],
            },
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
            return None

        return None

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
            r"^(what do you (know|remember)|recall|show memories)\s*",
            "",
            query,
            flags=re.I,
        ).strip()
        q = re.sub(r"^about\s+", "", q, flags=re.I).strip()
        stop = {"a", "an", "the", "my", "me", "about", "regarding", "on", "for", "of"}
        tokens = [t for t in re.split(r"\W+", q) if t and t.lower() not in stop]
        return " ".join(tokens) if tokens else q

    async def _step_knowledge(self, intent: Intent, message: str, ctx: dict[str, Any]) -> str:
        from sage.knowledge.interfaces import KnowledgeManager

        km = self._container.try_resolve(KnowledgeManager)
        if not km:
            return "knowledge=0"
        hits = await km.search(intent.subject or message, limit=3)
        ctx["knowledge"] = [f"{h.title}: {h.snippet}" for h in hits if h.snippet]
        return f"knowledge={len(hits)}"

    async def _step_store(self, intent: Intent, ctx: dict[str, Any]) -> str:
        from sage.memory.interfaces import MemorySystem
        from sage.memory.models import MemoryItem, MemoryType

        mem = self._container.try_resolve(MemorySystem)
        if not mem:
            return "Memory system is unavailable."
        fact = intent.subject.strip()
        if not fact:
            return "Nothing to remember."
        # Use cognitive store path if available
        store_fn = getattr(mem, "store_cognitive", None)
        if callable(store_fn):
            mid = await store_fn(
                MemoryItem(
                    type=MemoryType.LONG_TERM,
                    content=fact,
                    importance=0.75,
                    confidence=0.9,
                    source="user",
                    tags=["user_stated"],
                )
            )
        else:
            mid = await mem.store(
                MemoryItem(
                    type=MemoryType.LONG_TERM,
                    content=fact,
                    importance=0.75,
                    confidence=0.9,
                    source="user",
                    tags=["user_stated"],
                )
            )
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

        lib = self._container.try_resolve(SkillLibrary)  # type: ignore[type-abstract]
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

        de = self._container.try_resolve(DecisionEngine)  # type: ignore[type-abstract]
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

        cce = self._container.try_resolve(CognitiveContextEngine)  # type: ignore[type-abstract]
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

        cce = self._container.try_resolve(CognitiveContextEngine)  # type: ignore[type-abstract]
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
        # If earlier steps already produced a user-facing artifact for non-chat intents, use it
        artifacts = ctx.get("_artifacts") or []
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

        from sage.conversation.personality import build_system_prompt
        from sage.models.interfaces import CompletionRequest, Message, ModelRouter
        from sage.config.settings import Settings

        router = self._container.try_resolve(ModelRouter)
        if router is None:
            return f"I heard you, but no language model is configured. You said: «{message}»"

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
            extra_bits.append("Relevant memories:\n- " + "\n- ".join(ctx["memories"][:5]))
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

        system = build_system_prompt(extra="\n\n".join(extra_bits) if extra_bits else None)
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
