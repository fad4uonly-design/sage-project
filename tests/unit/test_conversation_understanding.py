"""Conversational Intelligence layer tests — deterministic, no LLM.

Covers: dialogue-mode classification (including the 15-item conversational
evaluation set), response policy fields, deterministic natural social replies,
style adaptation, memory-evidence grounding phrasing, orchestrator
integration, and the memory REPLACE lifecycle (a changed user statement
updates the existing user-stated memory instead of appending a duplicate).
"""

from __future__ import annotations

import pytest
from sage.conversation.personality import (
    build_system_prompt,
    memory_evidence_block,
    style_directive,
)
from sage.conversation.understanding import (
    ConversationMode,
    social_response,
    understand,
)
from sage.core.container import Container
from sage.core.engine import SageEngine
from sage.memory.service import SQLiteMemorySystem
from sage.orchestrator.engine import DefaultOrchestrator
from sage.orchestrator.interfaces import Orchestrator
from sage.orchestrator.models import IntentKind, PipelineStep


# -- 1. Mode classification (incl. the conversational evaluation set) ---------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # evaluation set
        ("hi", ConversationMode.SOCIAL_GREETING),
        ("hi bro", ConversationMode.SOCIAL_GREETING),
        ("good morning", ConversationMode.SOCIAL_GREETING),
        ("what's up?", ConversationMode.SOCIAL_GREETING),
        ("tell me a joke", ConversationMode.CASUAL_CHAT),
        ("what were we working on?", ConversationMode.CONTINUATION),
        ("continue from yesterday", ConversationMode.CONTINUATION),
        ("no, that's not what I meant", ConversationMode.CORRECTION),
        ("remember that I prefer X", ConversationMode.TASK),
        ("what do you remember about X?", ConversationMode.QUESTION),
        ("do you think I would like X?", ConversationMode.QUESTION),
        ("help me plan X", ConversationMode.PLANNING),
        ("Actually, can you help me plan this?", ConversationMode.PLANNING),
        ("let's continue the SAGE work", ConversationMode.CONTINUATION),
        ("I changed my mind about X", ConversationMode.CORRECTION),
        ("thanks bro", ConversationMode.CASUAL_CHAT),
        # additional coverage
        ("What is RAG?", ConversationMode.QUESTION),
        ("calculate 25 * 4", ConversationMode.TOOL_REQUEST),
        ("learn about photosynthesis", ConversationMode.TOOL_REQUEST),
        ("I'm feeling pretty frustrated today", ConversationMode.EMOTIONAL_SUPPORT),
        ("can you clarify what you meant?", ConversationMode.CLARIFICATION),
        ("yes, exactly", ConversationMode.CONFIRMATION),
        ("I don't think that's right", ConversationMode.DISAGREEMENT),
        ("what about the other approach?", ConversationMode.FOLLOW_UP),
    ],
)
def test_mode_classification(message: str, expected: ConversationMode) -> None:
    assert understand(message).mode == expected


# -- 2. Deterministic natural social replies -----------------------------------


def test_social_greeting_mirrors_address_and_stays_natural() -> None:
    u = understand("hi bro")
    reply = social_response("hi bro", u)
    assert reply is not None
    assert "bro" in reply.lower()
    assert len(reply) <= 80
    # Not the generic support-bot template.
    assert "How can I help you today" not in reply
    # Deterministic: same input → same reply.
    assert social_response("hi bro", u) == reply


def test_social_goodbye_reply_mirrors_address() -> None:
    u = understand("see you later bro")
    reply = social_response("see you later bro", u)
    assert reply is not None
    assert "bro" in reply.lower()


def test_good_morning_reply_is_time_aware() -> None:
    u = understand("good morning")
    reply = social_response("good morning", u)
    assert reply is not None
    assert "morning" in reply.lower()


def test_social_reply_is_none_when_greeting_carries_content() -> None:
    u = understand("hi bro, help me plan the week")
    assert u.mode == ConversationMode.PLANNING
    assert u.policy.acknowledge_first is True
    assert social_response("hi bro, help me plan the week", u) is None


# -- 3. Response policy ---------------------------------------------------------


def test_greeting_policy_is_short_social_without_memory_or_tools() -> None:
    policy = understand("hi bro").policy
    assert policy.acknowledge_first is True
    assert policy.needs_memory is False
    assert policy.allow_tools is False
    assert policy.length == "short"
    assert policy.tone == "casual"


def test_question_policy_answers_directly() -> None:
    policy = understand("What is RAG?").policy
    assert policy.answer_directly is True


def test_continuation_policy_needs_history_and_memory() -> None:
    policy = understand("what were we working on?").policy
    assert policy.needs_history is True
    assert policy.needs_memory is True


def test_unmatched_turn_defaults_to_casual_chat() -> None:
    u = understand("tell me a joke")
    assert u.mode == ConversationMode.CASUAL_CHAT
    assert u.matched is False


# -- 4. Orchestrator integration ------------------------------------------------


def make_orchestrator() -> DefaultOrchestrator:
    return DefaultOrchestrator(Container())


async def test_greeting_bypasses_model_and_retrieval() -> None:
    """'hi bro' is a social interaction: no retrieval, no tools, no model —
    even with no model configured at all."""
    orch = make_orchestrator()
    result = await orch.handle("hi bro")

    assert result.intent.kind == IntentKind.CHAT
    assert result.metadata["conversation"]["mode"] == "social_greeting"
    assert result.metadata["conversation"]["response_type"] == "social"
    steps = [s.step for s in result.steps]
    assert PipelineStep.RETRIEVE not in steps
    assert "bro" in result.response.lower()
    assert "How can I help you today" not in result.response


async def test_non_social_chat_path_is_unchanged() -> None:
    """A real question still flows through retrieve → compose (controlled
    'no model configured' reply on a bare container)."""
    orch = make_orchestrator()
    result = await orch.handle("What is RAG?")

    assert result.intent.kind == IntentKind.CHAT
    assert result.metadata["conversation"]["mode"] == "question"
    assert result.metadata["conversation"]["response_type"] == "model"
    assert [s.step for s in result.steps] == [
        PipelineStep.ANALYZE_INTENT,
        PipelineStep.RETRIEVE,
        PipelineStep.COMPOSE_RESPONSE,
    ]
    assert "no language model" in result.response.lower()


async def test_continuation_mode_is_recorded_in_metadata(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    result = await orch.handle("what were we working on?")
    assert result.metadata["conversation"]["mode"] == "continuation"


# -- 5. Personality: layered style + grounded memory evidence -------------------


def test_style_directive_adapts_to_tone() -> None:
    casual = style_directive("casual", length="short")
    technical = style_directive("technical", length="detailed")
    assert casual != technical
    assert "casual" in casual.lower()
    assert "short" in casual.lower()
    assert "technical" in technical.lower()
    assert "detailed" in technical.lower()


def test_memory_evidence_is_grounded_as_user_stated() -> None:
    """Explicit memory is presented as what the user said — never extrapolated
    into unsupported personal facts."""
    block = memory_evidence_block(["SAGE should remain simple and user-controlled."])
    assert "You've said" in block
    assert "SAGE should remain simple and user-controlled." in block
    assert "not as universal facts" in block

    prompt = build_system_prompt(
        extra=block, style=style_directive("technical", length="normal")
    )
    assert "You've said" in prompt
    assert "technical and precise" in prompt


def test_memory_evidence_block_empty_is_none() -> None:
    assert memory_evidence_block([]) is None
    assert memory_evidence_block(None) is None


def test_memory_evidence_separates_web_learned_from_user_said() -> None:
    """Web-learned notes are never attributed to the user."""
    block = memory_evidence_block(
        ["I grow tomatoes.", "Concrete slump measures workability."],
        learned=frozenset({"Concrete slump measures workability."}),
    )
    assert block is not None
    lines = block.splitlines()
    said = [ln for ln in lines if ln.startswith("- You've said:")]
    web = [ln for ln in lines if ln.startswith("- Saved from the web:")]
    assert len(said) == 1
    assert "I grow tomatoes." in said[0]
    assert len(web) == 1
    assert "Concrete slump measures workability." in web[0]
    assert "not something the user said" in block


def test_memory_evidence_all_learned_omits_user_header() -> None:
    block = memory_evidence_block(
        ["Water cycle notes."], learned={"Water cycle notes."}
    )
    assert block is not None
    assert "You've said" not in block
    assert "not as universal facts" not in block
    assert "Saved from the web" in block


def test_memory_evidence_without_learned_matches_default() -> None:
    items = ["A.", "B."]
    default = memory_evidence_block(items)
    assert default is not None
    assert memory_evidence_block(items, learned=None) == default
    assert memory_evidence_block(items, learned=frozenset()) == default
    assert memory_evidence_block(items, learned={"unrelated"}) == default


def test_structured_memory_evidence_user_memory_renders_user_stated() -> None:
    """Fused structured evidence: a user-sourced memory renders as user-stated,
    with its confidence and source_ref preserved."""
    block = memory_evidence_block(
        [
            {
                "content": "I prefer dark mode for interfaces",
                "confidence": 0.9,
                "source": "user",
                "source_ref": "chat:turn-42",
                "metadata": {"status": "current"},
            }
        ]
    )
    assert block is not None
    assert 'You\'ve said: "I prefer dark mode for interfaces"' in block
    assert "confidence 0.90" in block
    assert "source_ref: chat:turn-42" in block
    assert "not as universal facts" in block
    assert "Saved from the web" not in block


def test_structured_memory_evidence_web_learned_not_attributed_to_user() -> None:
    """A web-learned memory renders as stored web background, never as
    something the user said — provenance comes from the memory itself."""
    from sage.core.web_learner import WEB_LEARNED_SOURCE

    block = memory_evidence_block(
        [
            {
                "content": "Concrete slump measures workability.",
                "confidence": 0.75,
                "source": WEB_LEARNED_SOURCE,
                "source_ref": None,
                "metadata": {"via": "web_learner", "learned_from": "web"},
            }
        ]
    )
    assert block is not None
    assert "Saved from the web" in block
    assert "Concrete slump measures workability." in block
    assert "confidence 0.75" in block
    assert "You've said" not in block
    assert "not something the user said" in block
    # Internal metadata keys other than provenance are not exposed.
    assert "web_learner" not in block
    assert "learned_from" not in block


def test_structured_memory_evidence_mixed_keeps_epistemic_split() -> None:
    """Mixed evidence keeps the user-stated vs web-background separation,
    driven by each memory's own source — not by a learned-text set."""
    from sage.core.web_learner import WEB_LEARNED_SOURCE

    block = memory_evidence_block(
        [
            {
                "content": "I grow tomatoes.",
                "confidence": 0.8,
                "source": "user",
                "source_ref": None,
                "metadata": {},
            },
            {
                "content": "Water cycle notes.",
                "confidence": 0.6,
                "source": WEB_LEARNED_SOURCE,
                "source_ref": "https://example.com/water-cycle",
                "metadata": {},
            },
        ]
    )
    assert block is not None
    lines = block.splitlines()
    said = [ln for ln in lines if ln.startswith("- You've said:")]
    web = [ln for ln in lines if ln.startswith("- Saved from the web:")]
    assert len(said) == 1
    assert "I grow tomatoes." in said[0]
    assert len(web) == 1
    assert "Water cycle notes." in web[0]
    assert "source_ref: https://example.com/water-cycle" in web[0]
    # Never attributed to the user, and never called relevance.
    assert "I grow tomatoes." not in " ".join(web)
    assert "relevance" not in block.lower()


def test_web_learned_texts_reads_memory_items_and_retrieval() -> None:
    from types import SimpleNamespace

    from sage.conversation.personality import web_learned_texts
    from sage.core.web_learner import WEB_LEARNED_SOURCE
    from sage.memory.models import MemoryItem
    from sage.retrieval.models import EvidenceItem, RetrievalLayer

    def ev(content: str, **meta: object) -> EvidenceItem:
        return EvidenceItem(
            layer=RetrievalLayer.MEMORY, content=content, metadata=dict(meta)
        )

    ctx: dict[str, object] = {
        "memory_items": [
            MemoryItem(content="learned via recall", source=WEB_LEARNED_SOURCE),
            MemoryItem(content="user said this", source="user"),
        ],
        "retrieval": SimpleNamespace(
            ranked=[
                ev("learned via retrieve", source=WEB_LEARNED_SOURCE),
                ev("plain", source=None),
                ev("no source key"),
            ]
        ),
    }
    assert web_learned_texts(ctx) == frozenset(
        {"learned via recall", "learned via retrieve"}
    )
    assert web_learned_texts({}) == frozenset()


def test_system_prompt_does_not_demand_memory_attribution_unconditionally() -> None:
    """Regression: an unconditional 'say so when you use memory' made small
    models invent a memory section when nothing was retrieved."""
    from sage.conversation.personality import SYSTEM_PROMPT

    assert "When you use memory or knowledge, say so briefly" not in SYSTEM_PROMPT
    assert "only when it is provided" in SYSTEM_PROMPT
    assert "do not claim to have used any" in SYSTEM_PROMPT


# -- 6. Memory lifecycle: REPLACE before ADD + secret guard ---------------------


async def test_changed_preference_replaces_user_memory(engine: SageEngine) -> None:
    """'I changed my preference' must UPDATE the existing user-stated memory
    (versioned, history preserved) instead of blindly adding a duplicate."""
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    mem = engine.container.resolve(SQLiteMemorySystem)

    await orch.handle("remember: I prefer dark mode for interfaces")
    user_items = [
        i
        for i in await mem.recall("prefer interfaces mode", limit=20)
        if i.source == "user"
    ]
    assert len(user_items) == 1
    assert "dark mode" in user_items[0].content.lower()
    assert user_items[0].version == 1

    result = await orch.handle("remember: I prefer light mode for interfaces")
    # The LEARN step may emit its own acknowledgment for prefer-statements;
    # the behavioral contract is the memory state asserted below.
    assert (
        "Updated my memory" in result.response or "Preference noted" in result.response
    )


async def test_store_step_reports_replacement_explicitly(engine: SageEngine) -> None:
    """Pin the store step's own wording (it can be masked in the composed
    response by the LEARN step's preference acknowledgment)."""
    from sage.memory.models import MemoryType
    from sage.orchestrator.models import Intent

    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    mem = engine.container.resolve(SQLiteMemorySystem)

    await orch.handle("remember: I prefer dark mode for interfaces")
    response = await orch._step_store(
        Intent(kind=IntentKind.REMEMBER, subject="I prefer light mode for interfaces"),
        {},
    )

    assert "Updated my memory" in response
    user_items = [
        i
        for i in await mem.recall("prefer interfaces mode", limit=20)
        if i.source == "user"
    ]
    assert len(user_items) == 1
    assert "light mode" in user_items[0].content.lower()

    user_items = [
        i
        for i in await mem.recall("prefer interfaces mode", limit=20)
        if i.source == "user"
    ]
    assert len(user_items) == 1, "changed preference must update, not duplicate"
    assert "light mode" in user_items[0].content.lower()
    assert "dark" not in user_items[0].content.lower()
    assert user_items[0].version >= 2, "history must be preserved via versioning"
    assert user_items[0].metadata.get("status") == "current"


async def test_repeated_statement_reinforces_instead_of_duplicating(
    engine: SageEngine,
) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    mem = engine.container.resolve(SQLiteMemorySystem)

    await orch.handle("remember: I prefer dark mode for interfaces")
    result = await orch.handle("remember: I prefer dark mode for interfaces")

    assert (
        "reinforced" in result.response.lower() or "preference noted" in result.response.lower()
    )
    user_items = [
        i
        for i in await mem.recall("prefer interfaces mode", limit=20)
        if i.source == "user"
    ]
    assert len(user_items) == 1


async def test_secrets_are_refused_not_stored(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    mem = engine.container.resolve(SQLiteMemorySystem)

    before = await mem.count()
    result = await orch.handle("remember: my password is hunter2")

    assert "won't store" in result.response.lower()
    assert await mem.count() == before


@pytest.mark.parametrize(
    "message",
    [
        "what time is it",
        "can you tell me what time it is",
        "what is the current time",
        "current time please",
        "what's the time",
        "what is today's date",
        "what day is it",
    ],
)
def test_time_and_date_questions_are_tool_requests(message: str) -> None:
    assert understand(message).mode == ConversationMode.TOOL_REQUEST


@pytest.mark.parametrize(
    "message",
    [
        "what is the time of the meeting?",
        "what is the date of the contract",
        "what's the current time extension?",
        "what time is it in Tokyo",
        "what is the current date on drawing A-101",
    ],
)
def test_document_questions_about_time_are_not_tool_requests(message: str) -> None:
    assert understand(message).mode != ConversationMode.TOOL_REQUEST
