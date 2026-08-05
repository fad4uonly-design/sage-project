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
            r"^\s*(plan|create a plan|make a plan|help me plan)\b(.*)$",
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

        # 1) Absolute-priority intents (never/recall/status) always win
        for kind, pattern, conf in _PATTERNS:
            if kind not in {
                IntentKind.STATUS,
                IntentKind.REMEMBER,
                IntentKind.RECALL,
            }:
                continue
            m = pattern.match(text)
            if not m:
                continue
            return self._intent_from_match(kind, conf, m, text)

        # 2) Domain specialists beat generic plan/reason when keywords are clear
        domain_intent = self._domain_agent_intent(text)
        if domain_intent is not None and domain_intent.confidence >= 0.7:
            return domain_intent

        # 3) Remaining structured patterns
        for kind, pattern, conf in _PATTERNS:
            if kind in {
                IntentKind.STATUS,
                IntentKind.REMEMBER,
                IntentKind.RECALL,
            }:
                continue
            m = pattern.match(text)
            if not m:
                continue
            return self._intent_from_match(kind, conf, m, text)

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
        soft = self._domain_agent_intent(text)
        if soft is not None:
            return soft

        return Intent(
            kind=IntentKind.CHAT,
            confidence=0.5,
            subject=text,
            raw_message=text,
            hints=self._hints(IntentKind.CHAT, text),
        )

    def _intent_from_match(
        self,
        kind: IntentKind,
        conf: float,
        m: re.Match[str],
        text: str,
    ) -> Intent:
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

    def _domain_agent_intent(self, text: str) -> Intent | None:
        lower = text.lower()
        if any(
            k in lower
            for k in (
                "agriculture",
                "crop",
                "farm",
                "irrigation",
                "fertilizer",
                "blight",
                "harvest",
                "greenhouse",
                "soil",
                "pest",
                "tomato",
                "planting",
            )
        ):
            return Intent(
                kind=IntentKind.AGENT,
                confidence=0.78,
                subject=text,
                raw_message=text,
                entities={"domain": "agriculture"},
                hints=["domain:agriculture"],
            )
        if any(
            k in lower
            for k in (
                "invoice",
                "budget",
                "ledger",
                "accounting",
                "loan",
                "cash flow",
                "cashflow",
                "investment",
                "roi",
                "expense",
            )
        ):
            return Intent(
                kind=IntentKind.AGENT,
                confidence=0.75,
                subject=text,
                raw_message=text,
                entities={"domain": "finance"},
                hints=["domain:finance"],
            )
        # Business Intelligence Suite — route to specialized domains when clear
        bi_routes: list[tuple[str, tuple[str, ...], float]] = [
            (
                "marketing",
                ("marketing plan", "campaign", "branding", "positioning", "segmentation", "advertising"),
                0.8,
            ),
            (
                "sales",
                ("sales forecast", "sales pipeline", "lead pipeline", "quota", "pricing analysis"),
                0.78,
            ),
            (
                "operations",
                ("inventory", "procurement", "process optimization", "resource allocation", "logistics"),
                0.78,
            ),
            (
                "accounting",
                (
                    "journal entry",
                    "financial statements",
                    "ratio analysis",
                    "break-even",
                    "breakeven",
                    "bookkeeping",
                    "balance sheet",
                ),
                0.8,
            ),
            (
                "financial_planning",
                ("financial planning", "profitability analysis", "cash flow forecast"),
                0.78,
            ),
            ("hr", ("hiring plan", "headcount", "org design", "onboarding plan"), 0.78),
            (
                "project_management",
                ("project plan", "project schedule", "milestone monitoring", "raid log", "gantt"),
                0.78,
            ),
            (
                "market_research",
                ("market research", "customer research", "competitor research"),
                0.8,
            ),
            (
                "analytics",
                ("kpi dashboard", "trend analysis", "performance report", "business forecast"),
                0.78,
            ),
            (
                "risk_compliance",
                ("risk assessment", "compliance review", "regulatory"),
                0.8,
            ),
            (
                "strategy",
                ("strategic direction", "corporate strategy", "competitive strategy"),
                0.78,
            ),
            (
                "business",
                (
                    "swot",
                    "business plan",
                    "startup plan",
                    "feasibility",
                    "business model",
                    "go-to-market",
                    "gtm",
                    "expansion plan",
                ),
                0.75,
            ),
        ]
        for domain, keys, conf in bi_routes:
            if any(k in lower for k in keys):
                return Intent(
                    kind=IntentKind.AGENT,
                    confidence=conf,
                    subject=text,
                    raw_message=text,
                    entities={"domain": domain},
                    hints=[f"domain:{domain}", "suite:business_intelligence"],
                )
        if any(
            k in lower
            for k in (
                "write code",
                "implement",
                "debug",
                "refactor",
                "unit test",
                "pytest",
                "sage plugin",
                "traceback",
            )
        ):
            return Intent(
                kind=IntentKind.AGENT,
                confidence=0.72,
                subject=text,
                raw_message=text,
                entities={"domain": "programming"},
                hints=["domain:programming"],
            )
        return None

    def _hints(self, kind: IntentKind, text: str) -> list[str]:
        hints = [f"intent:{kind.value}"]
        if len(text) > 400:
            hints.append("long_message")
        return hints
