"""Intent analyzer — rule-based with extensible hooks for model assist later."""

from __future__ import annotations

import re
from typing import Any

from sage.orchestrator.models import Intent, IntentKind

_PATTERNS: list[tuple[IntentKind, re.Pattern[str], float]] = [
    (
        IntentKind.STATUS,
        re.compile(r"^\s*(status|system status|health|/status)\s*$", re.I),
        0.99,
    ),
    (
        IntentKind.REMEMBER,
        re.compile(
            r"^\s*(remember(?:\s+that)?|note(?:\s+that)?|don't forget)\s*[:\-]?\s*(.+)$",
            re.I | re.S,
        ),
        0.95,
    ),
    (
        IntentKind.RECALL,
        re.compile(
            r"^\s*(what do you (know|remember)|recall|show memories)\b(.*)$",
            re.I | re.S,
        ),
        0.95,
    ),
    (
        IntentKind.PLAN,
        re.compile(
            r"^\s*(plan|create a plan|make a plan|help me plan|schedule)\b(.*)$",
            re.I | re.S,
        ),
        0.9,
    ),
    (
        IntentKind.REASON,
        re.compile(
            r"^\s*(reason about|think about|analyze|should i|decide whether)\b(.*)$",
            re.I | re.S,
        ),
        0.9,
    ),
    (
        IntentKind.RESEARCH,
        re.compile(r"^\s*(research|investigate|look up|find out about)\b(.*)$", re.I | re.S),
        0.88,
    ),
    (
        IntentKind.DOCUMENT,
        re.compile(
            r"^\s*(ingest|summarize( document)?|analyze document|read file)\b(.*)$",
            re.I | re.S,
        ),
        0.88,
    ),
    (
        IntentKind.LEARN,
        re.compile(
            r"^\s*(prefer|i (like|prefer|want)|set preference)\b(.*)$",
            re.I | re.S,
        ),
        0.75,
    ),
]


class IntentAnalyzer:
    def analyze(self, message: str, *, context: dict[str, Any] | None = None) -> Intent:
        text = message.strip()
        if not text:
            return Intent(kind=IntentKind.UNKNOWN, confidence=0.0, raw_message=message)

        for kind, pattern, conf in _PATTERNS:
            m = pattern.match(text)
            if not m:
                continue
            groups = m.groups()
            subject = ""
            if kind == IntentKind.REMEMBER and len(groups) >= 2:
                subject = (groups[-1] or "").strip()
            elif kind in {
                IntentKind.RECALL,
                IntentKind.PLAN,
                IntentKind.REASON,
                IntentKind.RESEARCH,
                IntentKind.DOCUMENT,
                IntentKind.LEARN,
            }:
                subject = (groups[-1] or "").strip()
            return Intent(
                kind=kind,
                confidence=conf,
                subject=subject or text,
                raw_message=text,
                hints=self._hints(kind, text),
            )

        # Soft keyword signals for agent routing
        lower = text.lower()
        if any(k in lower for k in ("research", "investigate")):
            return Intent(
                kind=IntentKind.RESEARCH,
                confidence=0.6,
                subject=text,
                raw_message=text,
                hints=["keyword:research"],
            )
        if any(k in lower for k in ("agriculture", "crop", "farm", "irrigation")):
            return Intent(
                kind=IntentKind.AGENT,
                confidence=0.55,
                subject=text,
                raw_message=text,
                entities={"domain": "agriculture"},
                hints=["domain:agriculture"],
            )
        if any(k in lower for k in ("invoice", "budget", "ledger", "accounting")):
            return Intent(
                kind=IntentKind.AGENT,
                confidence=0.55,
                subject=text,
                raw_message=text,
                entities={"domain": "finance"},
                hints=["domain:finance"],
            )

        return Intent(
            kind=IntentKind.CHAT,
            confidence=0.5,
            subject=text,
            raw_message=text,
            hints=self._hints(IntentKind.CHAT, text),
        )

    def _hints(self, kind: IntentKind, text: str) -> list[str]:
        hints = [f"intent:{kind.value}"]
        if len(text) > 400:
            hints.append("long_message")
        return hints
