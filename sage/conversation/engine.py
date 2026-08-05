"""Conversation engine — orchestrates memory, reasoning, agents, and models."""

from __future__ import annotations

import re
from typing import Any

from sage.config.settings import Settings
from sage.conversation.context import DialogueContext
from sage.conversation.models import ConversationTurn, Session
from sage.conversation.personality import build_system_prompt
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import ConversationEvents, Event
from sage.logging import get_logger
from sage.utils.time import utcnow_iso

log = get_logger(__name__)

# Lightweight intent patterns for routing without an LLM
_REMEMBER_RE = re.compile(
    r"^\s*(remember(?:\s+that)?|note(?:\s+that)?|don't forget)\s*[:\-]?\s*(.+)$",
    re.I | re.S,
)
_RECALL_RE = re.compile(
    r"^\s*(what do you (know|remember)|recall|show memories)\b(.*)$",
    re.I | re.S,
)
_PLAN_RE = re.compile(r"^\s*(plan|create a plan|make a plan|help me plan)\b(.*)$", re.I | re.S)
_REASON_RE = re.compile(r"^\s*(reason about|think about|analyze|should i)\b(.*)$", re.I | re.S)
_STATUS_RE = re.compile(r"^\s*(status|system status|health)\s*$", re.I)


class DefaultConversationEngine(BaseRepository):
    def __init__(
        self,
        db: Database,
        events: EventBus,
        settings: Settings,
        container: Any,
    ) -> None:
        super().__init__(db)
        self._events = events
        self._settings = settings
        self._container = container
        self._sessions: dict[str, DialogueContext] = {}

    async def start_session(self, *, user_id: str = "default") -> Session:
        session = Session(user_id=user_id)
        await self.db.execute(
            """
            INSERT INTO conversations (id, user_id, started_at, ended_at, metadata)
            VALUES (?, ?, ?, NULL, '{}')
            """,
            (session.id, session.user_id, session.started_at),
        )
        self._sessions[session.id] = DialogueContext(
            session_id=session.id,
            user_id=user_id,
        )
        await self._events.publish(
            Event(
                type=ConversationEvents.SESSION_STARTED,
                payload={"session_id": session.id, "user_id": user_id},
                source="conversation",
            )
        )
        log.info("conversation.session_started", session_id=session.id, user_id=user_id)
        return session

    async def respond(self, session_id: str, message: str) -> ConversationTurn:
        ctx = await self._get_context(session_id)
        message = message.strip()
        if not message:
            raise ValueError("Empty message")

        # Assemble memory / knowledge context
        await self._enrich_context(ctx, message)

        # Intent routing
        reply, meta = await self._route(ctx, message)

        turn = ConversationTurn(
            session_id=session_id,
            turn_index=len(ctx.history),
            user_message=message,
            assistant_message=reply,
            metadata=meta,
        )
        await self.db.execute(
            """
            INSERT INTO conversation_turns
                (id, session_id, turn_index, user_message, assistant_message, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn.id,
                turn.session_id,
                turn.turn_index,
                turn.user_message,
                turn.assistant_message,
                self.dumps(turn.metadata),
                turn.created_at,
            ),
        )
        ctx.history.append(turn)
        # Bound in-memory history
        max_turns = self._settings.conversation.max_history_turns
        if len(ctx.history) > max_turns:
            ctx.history = ctx.history[-max_turns:]

        await self._events.publish(
            Event(
                type=ConversationEvents.TURN_COMPLETED,
                payload={
                    "session_id": session_id,
                    "turn_id": turn.id,
                    "user_message": message[:500],
                    "intent": meta.get("intent"),
                },
                source="conversation",
            )
        )
        return turn

    async def end_session(self, session_id: str) -> None:
        await self.db.execute(
            "UPDATE conversations SET ended_at = ? WHERE id = ?",
            (utcnow_iso(), session_id),
        )
        self._sessions.pop(session_id, None)
        await self._events.publish(
            Event(
                type=ConversationEvents.SESSION_ENDED,
                payload={"session_id": session_id},
                source="conversation",
            )
        )
        log.info("conversation.session_ended", session_id=session_id)

    async def _get_context(self, session_id: str) -> DialogueContext:
        if session_id in self._sessions:
            return self._sessions[session_id]
        row = await self.db.fetchone(
            "SELECT * FROM conversations WHERE id = ? AND ended_at IS NULL",
            (session_id,),
        )
        if row is None:
            raise KeyError(f"Unknown or ended session: {session_id}")
        ctx = DialogueContext(session_id=session_id, user_id=row["user_id"])
        turns = await self.db.fetchall(
            """
            SELECT * FROM conversation_turns
            WHERE session_id = ?
            ORDER BY turn_index ASC
            """,
            (session_id,),
        )
        for t in turns:
            ctx.history.append(
                ConversationTurn(
                    id=t["id"],
                    session_id=t["session_id"],
                    turn_index=t["turn_index"],
                    user_message=t["user_message"],
                    assistant_message=t["assistant_message"],
                    metadata=self.loads(t["metadata"], {}),
                    created_at=t["created_at"],
                )
            )
        self._sessions[session_id] = ctx
        return ctx

    async def _enrich_context(self, ctx: DialogueContext, message: str) -> None:
        from sage.knowledge.interfaces import KnowledgeManager
        from sage.learning.interfaces import LearningEngine
        from sage.memory.interfaces import MemorySystem

        mem = self._container.try_resolve(MemorySystem)
        if mem:
            items = await mem.recall(message, limit=5)
            ctx.recalled_memories = [m.content for m in items]

        km = self._container.try_resolve(KnowledgeManager)
        if km:
            hits = await km.search(message, limit=3)
            ctx.knowledge_snippets = [
                f"{h.title}: {h.snippet}" for h in hits if h.snippet
            ]

        learn = self._container.try_resolve(LearningEngine)
        if learn:
            # pull a couple common prefs if present
            for key in ("tone", "language", "name"):
                pref = await learn.get_preference(key)
                if pref:
                    ctx.preferences[key] = pref.value

    async def _route(self, ctx: DialogueContext, message: str) -> tuple[str, dict[str, Any]]:
        if _STATUS_RE.match(message):
            return await self._handle_status(), {"intent": "status"}

        m = _REMEMBER_RE.match(message)
        if m:
            fact = m.group(2).strip()
            return await self._handle_remember(fact), {"intent": "remember"}

        m = _RECALL_RE.match(message)
        if m:
            query = (m.group(3) or "").strip() or message
            return await self._handle_recall(query), {"intent": "recall"}

        m = _PLAN_RE.match(message)
        if m:
            goal = (m.group(2) or "").strip() or message
            return await self._handle_plan(goal), {"intent": "plan"}

        m = _REASON_RE.match(message)
        if m:
            problem = (m.group(2) or "").strip() or message
            return await self._handle_reason(problem, ctx), {"intent": "reason"}

        # Agent dispatch for domain-ish tasks
        if any(
            k in message.lower()
            for k in ("research", "investigate", "summarize document", "ingest")
        ):
            return await self._handle_agent(message), {"intent": "agent"}

        return await self._handle_chat(ctx, message), {"intent": "chat"}

    async def _handle_remember(self, fact: str) -> str:
        from sage.memory.interfaces import MemorySystem
        from sage.memory.models import MemoryItem, MemoryType

        mem = self._container.try_resolve(MemorySystem)
        if not mem:
            return "Memory system is unavailable."
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
        return f"Understood. I will remember that (id: {mid}).\n«{fact}»"

    async def _handle_recall(self, query: str) -> str:
        from sage.memory.interfaces import MemorySystem

        mem = self._container.try_resolve(MemorySystem)
        if not mem:
            return "Memory system is unavailable."
        # Strip leading intent words / "about" for better search
        q = re.sub(
            r"^(what do you (know|remember)|recall|show memories)\s*",
            "",
            query,
            flags=re.I,
        ).strip()
        q = re.sub(r"^about\s+", "", q, flags=re.I).strip()
        # Drop filler words so "about basil" / "my basil crop" still hits
        stop = {"a", "an", "the", "my", "me", "about", "regarding", "on", "for", "of"}
        tokens = [t for t in re.split(r"\W+", q) if t and t.lower() not in stop]
        q = " ".join(tokens) if tokens else q
        items = await mem.recall(q or "", limit=10)
        if not items:
            return "I don't have matching memories yet."
        lines = ["Here is what I remember:"]
        for i, item in enumerate(items, 1):
            lines.append(
                f"{i}. [{item.type.value} · importance {item.importance:.2f}] {item.content}"
            )
        return "\n".join(lines)

    async def _handle_plan(self, goal_text: str) -> str:
        from sage.agents.interfaces import AgentOrchestrator, AgentTask

        orch = self._container.try_resolve(AgentOrchestrator)
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

    async def _handle_reason(self, problem: str, ctx: DialogueContext) -> str:
        from sage.reasoning.interfaces import ReasoningEngine
        from sage.reasoning.models import ReasoningContext

        engine = self._container.try_resolve(ReasoningEngine)
        if not engine:
            return "Reasoning engine is unavailable."
        result = await engine.reason(
            problem,
            context=ReasoningContext(
                memories=list(ctx.recalled_memories),
                knowledge=list(ctx.knowledge_snippets),
            ),
        )
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

    async def _handle_agent(self, message: str) -> str:
        from sage.agents.interfaces import AgentOrchestrator, AgentTask

        orch = self._container.try_resolve(AgentOrchestrator)
        if not orch:
            return "Agent framework is unavailable."
        result = await orch.dispatch(AgentTask(description=message))
        if result.success:
            return result.output
        return result.error or "Agent task failed."

    async def _handle_status(self) -> str:
        from sage.core.engine import SageEngine

        engine = self._container.try_resolve(SageEngine)
        if engine is None:
            return "Engine handle unavailable."
        health = await engine.health()
        lines = [
            f"SAGE state: {engine.state.value}",
            f"Health: {health.level.value} — {health.message}",
            "Modules:",
        ]
        for m in health.modules:
            lines.append(f"  - {m.name}: {m.level.value} ({m.message})")
        return "\n".join(lines)

    async def _handle_chat(self, ctx: DialogueContext, message: str) -> str:
        from sage.models.interfaces import CompletionRequest, Message, ModelRouter

        router = self._container.try_resolve(ModelRouter)
        if router is None:
            return (
                "I heard you, but no language model is configured. "
                f"You said: «{message}»"
            )

        extra_bits: list[str] = []
        if ctx.recalled_memories:
            extra_bits.append(
                "Relevant memories:\n- " + "\n- ".join(ctx.recalled_memories[:5])
            )
        if ctx.knowledge_snippets:
            extra_bits.append(
                "Relevant knowledge:\n- " + "\n- ".join(ctx.knowledge_snippets[:3])
            )
        if ctx.preferences:
            extra_bits.append(f"User preferences: {ctx.preferences}")

        system = build_system_prompt(extra="\n\n".join(extra_bits) if extra_bits else None)
        messages = [Message(role="system", content=system)]
        for role, content in ctx.history_messages(
            limit=min(20, self._settings.conversation.max_history_turns)
        ):
            messages.append(Message(role=role, content=content))
        messages.append(Message(role="user", content=message))

        lm = router.get_language_model()
        settings = self._settings
        resp = await lm.complete(
            CompletionRequest(
                messages=messages,
                temperature=settings.models.temperature,
                max_tokens=settings.models.max_tokens,
            )
        )
        return resp.content
