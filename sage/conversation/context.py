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

    def history_messages(self, limit: int = 20) -> list[tuple[str, str]]:
        """Return (role, content) pairs for recent turns."""
        messages: list[tuple[str, str]] = []
        for turn in self.history[-limit:]:
            messages.append(("user", turn.user_message))
            messages.append(("assistant", turn.assistant_message))
        return messages
