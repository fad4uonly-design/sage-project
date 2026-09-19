"""Conversational understanding — deterministic dialogue-mode classification.

SAGE-native, rule-based (no extra LLM call): classifies each user turn into a
small controlled set of conversational modes and derives a lightweight
response policy. Capability routing (``IntentKind`` in the orchestrator) stays
untouched — this layer describes HOW to converse (tone, length, memory needs,
acknowledgment) rather than WHICH subsystem executes the request.

The model supplies language; SAGE supplies the conversational behavior.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum


class ConversationMode(StrEnum):
    SOCIAL_GREETING = "social_greeting"
    SOCIAL_GOODBYE = "social_goodbye"
    CASUAL_CHAT = "casual_chat"
    QUESTION = "question"
    EXPLANATION = "explanation"
    TASK = "task"
    PLANNING = "planning"
    RESEARCH = "research"
    CONTINUATION = "continuation"
    FOLLOW_UP = "follow_up"
    CLARIFICATION = "clarification"
    CORRECTION = "correction"
    CONFIRMATION = "confirmation"
    DISAGREEMENT = "disagreement"
    EMOTIONAL_SUPPORT = "emotional_support"
    TOOL_REQUEST = "tool_request"


@dataclass(frozen=True)
class ResponsePolicy:
    """Structured response policy passed to the composition step (not a prompt)."""

    acknowledge_first: bool = False
    answer_directly: bool = True
    needs_memory: bool = False
    needs_history: bool = True
    allow_tools: bool = False
    tone: str = "neutral"  # casual | neutral | technical | focused | serious | warm
    length: str = "normal"  # short | normal | detailed
    follow_up: bool = False


#: Per-mode policies — the smallest policy that makes each mode behave well.
_POLICIES: dict[ConversationMode, ResponsePolicy] = {
    ConversationMode.SOCIAL_GREETING: ResponsePolicy(
        acknowledge_first=True,
        answer_directly=False,
        needs_memory=False,
        needs_history=False,
        allow_tools=False,
        tone="casual",
        length="short",
    ),
    ConversationMode.SOCIAL_GOODBYE: ResponsePolicy(
        acknowledge_first=True,
        answer_directly=False,
        needs_memory=False,
        needs_history=False,
        allow_tools=False,
        tone="casual",
        length="short",
    ),
    ConversationMode.CASUAL_CHAT: ResponsePolicy(tone="casual", length="short"),
    ConversationMode.QUESTION: ResponsePolicy(),
    ConversationMode.EXPLANATION: ResponsePolicy(length="detailed"),
    ConversationMode.TASK: ResponsePolicy(allow_tools=True, tone="focused"),
    ConversationMode.PLANNING: ResponsePolicy(
        tone="focused", length="detailed", follow_up=True
    ),
    ConversationMode.RESEARCH: ResponsePolicy(
        allow_tools=True, needs_memory=True, length="detailed"
    ),
    ConversationMode.CONTINUATION: ResponsePolicy(needs_memory=True),
    ConversationMode.FOLLOW_UP: ResponsePolicy(),
    ConversationMode.CLARIFICATION: ResponsePolicy(
        answer_directly=False, follow_up=True, length="short"
    ),
    ConversationMode.CORRECTION: ResponsePolicy(acknowledge_first=True),
    ConversationMode.CONFIRMATION: ResponsePolicy(acknowledge_first=True),
    ConversationMode.DISAGREEMENT: ResponsePolicy(acknowledge_first=True),
    ConversationMode.EMOTIONAL_SUPPORT: ResponsePolicy(
        acknowledge_first=True,
        answer_directly=False,
        tone="warm",
    ),
    ConversationMode.TOOL_REQUEST: ResponsePolicy(allow_tools=True),
}


@dataclass(frozen=True)
class ConversationUnderstanding:
    """What SAGE understood about the current turn as a conversation."""

    mode: ConversationMode
    policy: ResponsePolicy
    matched: bool = False  # True when a deterministic rule fired
    acknowledge_prefix: bool = False  # greeting stripped; content follows

    @property
    def is_social(self) -> bool:
        return self.mode in {
            ConversationMode.SOCIAL_GREETING,
            ConversationMode.SOCIAL_GOODBYE,
        }


# -- deterministic rules (ordered; first match wins) ---------------------------

_ADDRESS_TERM = r"(?:bro|dude|man|fam|chief|boss|mate|friend|there|everyone|y'all)?"
_GREETING_ONLY = re.compile(
    r"^\s*(?:hi|hey|hello|yo|howdy|sup|what'?s up|good (?:morning|afternoon|evening))"
    r"\b[!,. ]*" + _ADDRESS_TERM + r"[!.? 👊👋☀️]*$",
    re.I,
)
_GOODBYE_ONLY = re.compile(
    r"^\s*(?:bye|goodbye|good ?night|see (?:you|ya)|talk (?:to you )?later|catch you later"
    r"|later|gotta go(?: now)?)\b[!,. !?👋]*(?:"
    r"(?:bro|dude|man|fam|chief|boss|mate|everyone|y'all|later|soon|then|now|tomorrow)"
    r"[!,. !?👋]*)*$",
    re.I,
)
_GREETING_PREFIX = re.compile(
    r"^\s*(?:hi|hey|hello|yo|howdy|sup|what'?s up|good (?:morning|afternoon|evening))\b"
    r"[!,. ]*",
    re.I,
)
_GOODBYE_PREFIX = re.compile(
    r"^\s*(?:bye|goodbye|good ?night|see (?:you|ya)|talk later|catch you later|later|gotta go)\b"
    r"[!,. ]*",
    re.I,
)
_THANKS = re.compile(r"^\s*(?:thanks|thank you|thx|ty)\b", re.I)
_CORRECTION = re.compile(
    r"^\s*(?:no\b|that'?s not|not what i meant|wrong|"
    r"i (?:changed my mind|meant|disagree with that)|that'?s (?:wrong|incorrect))\b",
    re.I,
)
_CORRECTION_ANY = re.compile(r"\b(?:changed my mind|i meant|not what i meant)\b", re.I)
_CLARIFICATION = re.compile(r"\b(?:what do you mean|can you clarify|clarify|i'?m confused)\b", re.I)
_CONFIRMATION = re.compile(r"^\s*(?:yes|yeah|yep|correct|exactly|sure|that'?s right|right)\b", re.I)
_DISAGREEMENT = re.compile(r"\b(?:i don'?t think|disagree|not sure i agree|beg to differ)\b", re.I)
_EMOTIONAL = re.compile(
    r"\b(?:i'?m (?:sad|upset|frustrated|angry|stressed|anxious|tired|exhausted|overwhelmed)"
    r"|i'?m feeling (?:pretty |really |very |so )?(?:sad|down|low|frustrated|stressed"
    r"|anxious|tired|overwhelmed)"
    r"|feeling (?:down|sad|low|rough)|had a (?:bad|rough|tough) (?:day|week))\b",
    re.I,
)
_CONTINUATION = re.compile(
    r"\b(?:continue|pick (?:this|it|up) |where (?:were we|did we leave)|what were we"
    r"|resume|from yesterday|from where we (?:stopped|left)|earlier)\b",
    re.I,
)
_FOLLOW_UP = re.compile(r"^\s*(?:what about|and what|and also|also,?|and then)\b", re.I)
_TOOL_REQUEST = re.compile(r"\b(?:calculate|compute|convert|learn about|search the web)\b", re.I)
_REMEMBER_STATED = re.compile(r"^\s*(?:remember|note|don'?t forget|keep in mind)\b", re.I)
_PLANNING = re.compile(r"\b(?:plan|schedule|organize|roadmap)\b", re.I)
_RESEARCH = re.compile(r"\b(?:research|investigate|look up|find out)\b", re.I)
_TASK = re.compile(r"\b(?:help me|can you|could you|fix|implement|debug|write|build)\b", re.I)
_EXPLANATION = re.compile(r"^\s*(?:explain|how (?:do|does)|tell me about)\b", re.I)
_QUESTION = re.compile(
    r"\?\s*$|^\s*(?:what|why|how|who|when|where|which|is|are|do|does|did|can|could|should)\b",
    re.I,
)
_ADDRESS = re.compile(r"\b(?:bro|dude|man|fam|chief|boss|mate)\b", re.I)


def _pick(message: str, pool: list[str]) -> str:
    """Stable deterministic variant choice (same message → same reply)."""
    digest = hashlib.sha256(message.lower().strip().encode("utf-8")).digest()
    return pool[digest[0] % len(pool)]


def social_response(message: str, understanding: ConversationUnderstanding) -> str | None:
    """Deterministic natural social reply for greeting/goodbye-only turns.

    Returns ``None`` when the turn carries real content (the normal pipeline
    handles it) or the mode is not social. Variants are picked deterministically
    per message and the user's address term is mirrored back, so replies feel
    personal without being one hardcoded template.
    """
    if not understanding.is_social:
        return None
    text = message.strip()
    addr_match = _ADDRESS.search(text)
    addr = f" {addr_match.group(0).lower()}" if addr_match else ""
    if understanding.mode is ConversationMode.SOCIAL_GREETING:
        if re.search(r"\bgood (?:morning|afternoon|evening)\b", text, re.I):
            part = "morning" if "morning" in text.lower() else "day"
            return _pick(
                text,
                [
                    f"Good {part}{addr}! ☀️ How's it going?",
                    f"Good {part}{addr}! ☀️ What's first today?",
                ],
            )
        return _pick(
            text,
            [
                f"Hey{addr}! 👋 What's up?",
                f"Hey{addr}! 👊 Good to see you. What's on your mind?",
                f"Yo{addr}! 👋 What are we up to today?",
            ],
        )
    # SOCIAL_GOODBYE
    return _pick(
        text,
        [
            f"Later{addr}! 👋",
            f"See you{addr} — take care!",
            f"Catch you later{addr}! 👋",
        ],
    )


def understand(message: str) -> ConversationUnderstanding:
    """Classify a user turn into a conversational mode + response policy.

    Deterministic and cheap: regex/keyword rules only, never a model call.
    A leading social word with substantial content classifies by the content
    and only flags an acknowledgment (``acknowledge_prefix``).
    """
    text = message.strip()
    if not text:
        return ConversationUnderstanding(
            mode=ConversationMode.CASUAL_CHAT,
            policy=_POLICIES[ConversationMode.CASUAL_CHAT],
        )

    # Social-only turns → deterministic social path.
    if _GREETING_ONLY.match(text):
        return ConversationUnderstanding(
            mode=ConversationMode.SOCIAL_GREETING,
            policy=_POLICIES[ConversationMode.SOCIAL_GREETING],
            matched=True,
        )
    if _GOODBYE_ONLY.match(text):
        return ConversationUnderstanding(
            mode=ConversationMode.SOCIAL_GOODBYE,
            policy=_POLICIES[ConversationMode.SOCIAL_GOODBYE],
            matched=True,
        )

    # Leading social word + content → classify content, acknowledge first.
    acknowledge_prefix = False
    rest = text
    greeting_match = _GREETING_PREFIX.match(text)
    goodbye_match = _GOODBYE_PREFIX.match(text)
    if greeting_match:
        rest = text[greeting_match.end() :].strip()
        acknowledge_prefix = True
    elif goodbye_match:
        rest = text[goodbye_match.end() :].strip()
        acknowledge_prefix = True
    if _THANKS.match(rest or ""):
        return ConversationUnderstanding(
            mode=ConversationMode.CASUAL_CHAT,
            policy=ResponsePolicy(
                tone="casual",
                length="short",
                acknowledge_first=True,
                answer_directly=False,
            ),
            matched=True,
            acknowledge_prefix=acknowledge_prefix,
        )
    text = rest or text

    def result(mode: ConversationMode) -> ConversationUnderstanding:
        base = _POLICIES[mode]
        if not acknowledge_prefix:
            return ConversationUnderstanding(mode=mode, policy=base, matched=True)
        return ConversationUnderstanding(
            mode=mode,
            policy=ResponsePolicy(
                acknowledge_first=True,
                answer_directly=base.answer_directly,
                needs_memory=base.needs_memory,
                needs_history=base.needs_history,
                allow_tools=base.allow_tools,
                tone=base.tone,
                length=base.length,
                follow_up=base.follow_up,
            ),
            matched=True,
            acknowledge_prefix=True,
        )

    if _CORRECTION.search(text) or _CORRECTION_ANY.search(text):
        return result(ConversationMode.CORRECTION)
    if _CLARIFICATION.search(text):
        return result(ConversationMode.CLARIFICATION)
    if _CONFIRMATION.match(text):
        return result(ConversationMode.CONFIRMATION)
    if _DISAGREEMENT.search(text):
        return result(ConversationMode.DISAGREEMENT)
    if _EMOTIONAL.search(text):
        return result(ConversationMode.EMOTIONAL_SUPPORT)
    if _CONTINUATION.search(text):
        return result(ConversationMode.CONTINUATION)
    if _FOLLOW_UP.match(text):
        return result(ConversationMode.FOLLOW_UP)
    if _TOOL_REQUEST.search(text):
        return result(ConversationMode.TOOL_REQUEST)
    if _REMEMBER_STATED.match(text):
        return result(ConversationMode.TASK)
    if _PLANNING.search(text):
        return result(ConversationMode.PLANNING)
    if _RESEARCH.search(text):
        return result(ConversationMode.RESEARCH)
    if _TASK.search(text):
        return result(ConversationMode.TASK)
    if _QUESTION.search(text):
        return result(ConversationMode.QUESTION)
    if _EXPLANATION.match(text):
        return result(ConversationMode.EXPLANATION)

    # Unmatched: plain casual conversation (still valid, just not classified).
    return ConversationUnderstanding(
        mode=ConversationMode.CASUAL_CHAT,
        policy=(
            ResponsePolicy(
                tone="casual",
                length="short",
                acknowledge_first=True,
                answer_directly=False,
            )
            if acknowledge_prefix
            else _POLICIES[ConversationMode.CASUAL_CHAT]
        ),
        matched=False,
    )
