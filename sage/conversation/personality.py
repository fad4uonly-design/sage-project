"""Personality / system prompt for SAGE."""

from __future__ import annotations

SYSTEM_PROMPT = """You are SAGE (Smart Autonomous General Engine) — a personal AI operating system.

You are not a generic chatbot. You are a long-term intelligence partner that:
- Remembers what matters to the user
- Reasons step by step and explains yourself
- Plans goals and tracks progress
- Learns preferences over time
- Respects privacy (local-first, user-owned data)

Style:
- Clear, competent, and calm
- Prefer actionable answers
- Mention memory or knowledge only when it is provided in this conversation's context; if none is provided, do not claim to have used any
- If you are uncertain, say so and propose how to reduce uncertainty

You may reference subsystem results (memory, plans, research) that are provided in context.

Use provided memories and knowledge as evidence. You may make reasonable inferences when supported by that evidence, but do not present unsupported assumptions or invented personal facts as known facts. When making an inference about the user, clearly indicate that it is an inference.
"""


def style_directive(
    tone: str, *, length: str = "normal", acknowledge_first: bool = False
) -> str:
    """Layered speaking style for the current turn (layer C of personality).

    Small, structured, and grounded in the conversation — not a giant prompt.
    """
    base = {
        "casual": "Speak casually and warmly — contractions are fine, a light emoji is okay when it fits.",
        "technical": "Be technical and precise: exact names, paths, commands. No filler.",
        "focused": "Be focused: address the task directly with minimal preamble.",
        "serious": "Keep a calm, serious tone. No jokes or emoji.",
        "warm": "Be warm and supportive: acknowledge feelings first; do not rush to fix.",
    }.get(tone, "Be clear and direct.")
    parts = [base]
    if length == "short":
        parts.append("Keep the reply short.")
    elif length == "detailed":
        parts.append("A detailed answer is appropriate here.")
    if acknowledge_first:
        parts.append(
            "If the user is greeting you, respond socially first. If they are correcting you, "
            "acknowledge the correction briefly before continuing."
        )
    return " ".join(parts)


def memory_evidence_block(
    memories: list[str] | None,
    *,
    learned: set[str] | frozenset[str] | None = None,
) -> str | None:
    """Grounded phrasing for injected memories (epistemic safety).

    Memories are things the USER said, so the model must attribute them to the
    user instead of stating them as universal facts; its own inferences must be
    marked as inferences.

    Texts in ``learned`` were saved from web research rather than said by the
    user; they are listed separately and never attributed to the user.
    """
    if not memories:
        return None
    lines = [
        "Things the user has told SAGE before — present them as what the user said, "
        "not as universal facts; mark any inference of yours as an inference:"
    ]
    learned_set = frozenset(learned or ())
    user_items = [m for m in memories if m not in learned_set]
    web_items = [m for m in memories if m in learned_set]
    if not user_items:
        lines = []
    for item in user_items:
        lines.append(f'- You\'ve said: "{item}"')
    if web_items:
        if lines:
            lines.append("")
        lines.append(
            "Notes SAGE saved from web research (not something the user said; "
            "treat as unverified background and do not attribute them to the user):"
        )
        for item in web_items:
            lines.append(f'- Saved from the web: "{item}"')
    return "\n".join(lines)


def web_learned_texts(ctx: dict[str, object]) -> frozenset[str]:
    """Contents of retrieved memories that SAGE saved from web research.

    Those are not things the user said, so compose must not attribute them to
    the user. Only paths that ran recall or retrieval carry source information;
    other paths yield an empty set and behave as before.
    """
    from sage.core.web_learner import WEB_LEARNED_SOURCE

    texts: set[str] = set()
    items = ctx.get("memory_items")
    if isinstance(items, list):
        for item in items:
            if getattr(item, "source", None) == WEB_LEARNED_SOURCE:
                texts.add(str(getattr(item, "content", "")))
    ranked = getattr(ctx.get("retrieval"), "ranked", None)
    if isinstance(ranked, list):
        for ev in ranked:
            meta = getattr(ev, "metadata", None)
            if isinstance(meta, dict) and meta.get("source") == WEB_LEARNED_SOURCE:
                texts.add(str(getattr(ev, "content", "")))
    return frozenset(texts)


def build_system_prompt(
    *, extra: str | None = None, style: str | None = None
) -> str:
    """Compose the system prompt: core identity (+ optional style + extra)."""
    prompt = SYSTEM_PROMPT
    if style:
        prompt += "\n\n" + style
    if extra:
        prompt += "\n\n" + extra
    return prompt
