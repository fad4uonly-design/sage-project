"""Conversation context assembly."""

from __future__ import annotations

from dataclasses import dataclass, field

from sage.conversation.models import ConversationTurn


@dataclass
class DialogueContext:
    session_id: str
    user_id: str
    history: list[ConversationTurn] = field(default_factory=list)
    recalled_memories: list[str] = field(default_factory=list)
    knowledge_snippets: list[str] = field(default_factory=list)
    preferences: dict[str, object] = field(default_factory=dict)
    # Short-lived conversational state (layer C) — describes the conversation,
    # never invents facts about the user. Promoted to memory only when the user
    # states something durable.
    mode: str | None = None
    previous_mode: str | None = None
    topic: str | None = None
    previous_topic: str | None = None
    last_response_type: str | None = None
    pending_correction: bool = False

    def note_turn(
        self,
        *,
        mode: str | None = None,
        topic: str | None = None,
        response_type: str | None = None,
    ) -> None:
        """Roll the short-lived state forward after one turn."""
        if mode and self.mode and mode != self.mode:
            self.previous_mode = self.mode
        if mode:
            self.mode = mode
        if topic and topic != self.topic:
            self.previous_topic = self.topic
            self.topic = topic
        if response_type:
            self.last_response_type = response_type
        if mode == "correction":
            self.pending_correction = True

    def state_snapshot(self) -> dict[str, str | None]:
        """Read-only view passed to the orchestrator with each turn."""
        return {
            "mode": self.mode,
            "previous_mode": self.previous_mode,
            "topic": self.topic,
            "previous_topic": self.previous_topic,
            "last_response_type": self.last_response_type,
        }

    def history_messages(self, limit: int = 20) -> list[tuple[str, str]]:
        """Return (role, content) pairs for recent turns."""
        messages: list[tuple[str, str]] = []
        for turn in self.history[-limit:]:
            messages.append(("user", turn.user_message))
            messages.append(("assistant", turn.assistant_message))
        return messages
