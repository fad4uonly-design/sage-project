"""Personality / system prompt for SAGE."""

from __future__ import annotations

from typing import Any

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
    memories: list[str] | list[dict[str, Any]] | None,
    *,
    learned: set[str] | frozenset[str] | None = None,
) -> str | None:
    """Grounded phrasing for injected memories (epistemic safety).

    Accepts either the legacy ``list[str]`` of memory contents or structured
    provenance dicts (``content``/``confidence``/``source``/``source_ref``/
    ``metadata``) from the fused cognitive context. With structured evidence,
    attribution follows the memory's actual provenance: items stamped with
    the web-learned source are presented as stored background, never as
    things the user said; everything else is presented as what the user said.
    No provenance is fabricated: a memory without source information is
    rendered as user-stated (the legacy contract), and confidence is shown
    as confidence — never labeled as relevance.

    Texts in ``learned`` were saved from web research rather than said by the
    user; they are listed separately and never attributed to the user.
    """
    if not memories:
        return None
    if not all(isinstance(m, dict) for m in memories):
        # Legacy string path — unchanged behavior.
        return _memory_evidence_block_strings(
            [str(m) for m in memories], learned=learned
        )
    return _memory_evidence_block_structured(memories)


def _memory_evidence_block_strings(
    memories: list[str],
    *,
    learned: set[str] | frozenset[str] | None,
) -> str | None:
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


def _memory_evidence_block_structured(
    memories: list[dict[str, Any]],
) -> str | None:
    """Render structured fused memory evidence with its actual provenance."""
    from sage.core.web_learner import WEB_LEARNED_SOURCE

    def _source_of(item: dict[str, Any]) -> str | None:
        source = item.get("source")
        if not source:
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                source = metadata.get("source")
        return str(source).strip() if source else None

    def _ref_of(item: dict[str, Any]) -> str | None:
        ref = item.get("source_ref")
        if not ref:
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                ref = metadata.get("source_ref")
        return str(ref).strip() if ref else None

    def _confidence_of(item: dict[str, Any]) -> float | None:
        try:
            value = float(item.get("confidence"))
        except (TypeError, ValueError):
            return None
        return value

    def _provenance_suffix(item: dict[str, Any]) -> str:
        parts: list[str] = []
        ref = _ref_of(item)
        if ref:
            parts.append(f"source_ref: {ref}")
        elif (source := _source_of(item)) and source != WEB_LEARNED_SOURCE:
            parts.append(f"source: {source}")
        confidence = _confidence_of(item)
        if confidence is not None:
            parts.append(f"confidence {confidence:.2f}")
        return f" ({'; '.join(parts)})" if parts else ""

    user_items: list[tuple[str, str]] = []  # (content, provenance suffix)
    web_items: list[tuple[str, str]] = []
    for item in memories:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        suffix = _provenance_suffix(item)
        if _source_of(item) == WEB_LEARNED_SOURCE:
            web_items.append((content, suffix))
        else:
            user_items.append((content, suffix))

    lines: list[str] = []
    if user_items:
        lines.append(
            "Things the user has told SAGE before — present them as what the user said, "
            "not as universal facts; mark any inference of yours as an inference:"
        )
        for content, suffix in user_items:
            lines.append(f'- You\'ve said: "{content}"{suffix}')
    if web_items:
        if lines:
            lines.append("")
        lines.append(
            "Notes SAGE saved from web research (not something the user said; "
            "treat as unverified background and do not attribute them to the user):"
        )
        for content, suffix in web_items:
            lines.append(f'- Saved from the web: "{content}"{suffix}')
    return "\n".join(lines) if lines else None


def evidence_block(ranked: object) -> str | None:
    """Provenance-aware evidence for the model prompt, from ranked EvidenceItems.

    Renders ``RetrievalResult.ranked`` concisely — content plus layer,
    confidence, and source reference (never the raw ``score``/relevance, which
    is a retrieval signal, not evidence confidence). Returns ``None`` when no
    usable evidence is present so callers fall back to legacy string blocks.

    Content lines intentionally mirror ``memory_evidence_block`` attribution:
    memory-layer lines are phrased as what the user said; other layers are
    presented as stored background with their layer named.
    """
    if not isinstance(ranked, list) or not ranked:
        return None
    lines = [
        "Retrieved evidence — content, its layer, confidence, and source "
        "(cite the [n] numbers when you use them; memories are things the "
        "user said, other layers are stored background, not user statements):"
    ]
    shown = 0
    for position, item in enumerate(ranked, start=1):
        content = str(getattr(item, "content", "") or "").strip()
        if not content:
            continue
        layer = getattr(getattr(item, "layer", None), "value", None) or str(
            getattr(item, "layer", "unknown")
        )
        try:
            confidence = float(getattr(item, "confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        source_ref = getattr(item, "source_ref", None)
        source = str(source_ref).strip() if source_ref else None
        metadata = getattr(item, "metadata", None)
        if not source and isinstance(metadata, dict):
            for key in ("source", "path", "document_id"):
                value = metadata.get(key)
                if value:
                    source = str(value).strip()
                    break
        provenance = f" | source: {source}" if source else ""
        if layer == "memory":
            line = (
                f"[{position}] [memory | confidence {confidence:.2f}] "
                f'You\'ve said: "{content}"{provenance}'
            )
        else:
            line = (
                f"[{position}] [{layer} | confidence {confidence:.2f}] "
                f"{content}{provenance}"
            )
        lines.append(line)
        shown += 1
        if shown >= 8:
            break
    return "\n".join(lines) if shown else None


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
