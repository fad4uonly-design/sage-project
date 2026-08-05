"""Conversation engine — sessions, history, delegates cognition to Orchestrator."""

from __future__ import annotations

from typing import Any

from sage.config.settings import Settings
from sage.conversation.context import DialogueContext
from sage.conversation.models import ConversationTurn, Session
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import ConversationEvents, Event
from sage.logging import get_logger
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class DefaultConversationEngine(BaseRepository):
    """
    Conversation surface.

    Flow:
      User message → session/history → Orchestrator → response → persist turn
    """

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

        # Preferences for orchestrator context
        await self._load_preferences(ctx)

        orch_context = {
            "session_id": session_id,
            "user_id": ctx.user_id,
            "history": ctx.history_messages(
                limit=min(20, self._settings.conversation.max_history_turns)
            ),
            "preferences": dict(ctx.preferences),
        }

        from sage.orchestrator.interfaces import Orchestrator

        orch = self._container.try_resolve(Orchestrator)
        if orch is None:
            # Fallback if orchestrator not loaded (should not happen in normal boot)
            reply = f"[no orchestrator] {message}"
            meta: dict[str, Any] = {"intent": "fallback"}
        else:
            result = await orch.handle(
                message,
                session_id=session_id,
                user_id=ctx.user_id,
                context=orch_context,
            )
            reply = result.response
            meta = {
                "intent": result.intent.kind.value,
                "intent_confidence": result.intent.confidence,
                "plan_id": result.plan_id,
                "steps": [
                    {
                        "step": s.step.value,
                        "success": s.success,
                        "duration_ms": s.duration_ms,
                        "error": s.error,
                    }
                    for s in result.steps
                ],
                **result.metadata,
            }
            # Keep recalled content on dialogue context for inspection
            ctx.recalled_memories = list(orch_context.get("memories") or [])
            ctx.knowledge_snippets = list(orch_context.get("knowledge") or [])

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
        # Session continuity: remember last turn blurb
        try:
            from sage.context.engine import CognitiveContextEngine

            cce = self._container.try_resolve(CognitiveContextEngine)
            if cce:
                blurb = f"User: {message[:120]} | SAGE: {reply[:160]}"
                await cce._set_state("last_conversation_summary", blurb)  # noqa: SLF001
        except Exception:
            pass
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

    async def _load_preferences(self, ctx: DialogueContext) -> None:
        from sage.learning.interfaces import LearningEngine

        learn = self._container.try_resolve(LearningEngine)
        if not learn:
            return
        for key in ("tone", "language", "name"):
            pref = await learn.get_preference(key)
            if pref:
                ctx.preferences[key] = pref.value
