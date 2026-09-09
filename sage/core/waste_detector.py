"""WasteDetector: cheap, heuristic pre-checks that run BEFORE any model call,
memory search, or tool invocation. This must stay cheaper than the thing
it's gating, or it becomes waste itself.

Maps to the ten waste categories:

  1. Duplicate thinking      -> flagged via task-hash cache
  2. Duplicate knowledge     -> deferred to MemoryInterface (has_similar)
  3. Unnecessary retrieval   -> evaluate(memory_hit=...)
  4. Unnecessary escalation  -> classify_complexity()
  5. Unnecessary tool calls  -> needs_tool()
  6. Unnecessary computation -> is_derivable()  (stub, hook for symbolic checks)
  7. Rework                  -> failed_before() / record_failure()
  8. Waiting                 -> not modeled here (belongs in the scheduler/queue)
  9. Overprocessing          -> requested_scope()  (folded into complexity)
 10. Human waste             -> repeated_pattern() -> should become a Skill
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum


class Complexity(Enum):
    TRIVIAL = "trivial"    # lookup / definition / single fact
    MODERATE = "moderate"  # requires some reasoning, single-step tool use ok
    COMPLEX = "complex"    # multi-step reasoning, multiple tools/sources


@dataclass
class WasteReport:
    duplicate_of_recent: bool = False
    likely_in_memory: bool = False
    complexity: Complexity = Complexity.MODERATE
    needs_tool: bool = False
    previously_failed: bool = False
    recommend_skill_extraction: bool = False
    notes: list[str] = field(default_factory=list)


class WasteDetector:
    """Stateful within a session: remembers seen/failed request hashes so the
    ValueRouter can pull the cheap levers before anything expensive runs."""

    def __init__(self) -> None:
        # task_hash -> times seen, for duplicate / repeated-pattern detection
        self._seen: dict[str, int] = {}
        self._failed_hashes: set[str] = set()

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16]

    def record_failure(self, request_text: str) -> None:
        """Jidoka: mark this request as having failed so rework is flagged."""
        self._failed_hashes.add(self._hash(request_text))

    def failed_before(self, request_text: str) -> bool:
        return self._hash(request_text) in self._failed_hashes

    def is_derivable(self, request_text: str) -> bool:
        """Stub hook for symbolic/derivable checks (waste category 6).
        Deliberately returns False until a real derivability check exists."""
        return False

    def classify_complexity(self, request_text: str) -> Complexity:
        """Cheap heuristic complexity classifier. Replace with a small local
        model or a rules engine as SAGE matures — but keep it cheap."""
        text = request_text.lower().strip()
        word_count = len(text.split())

        trivial_markers = (
            "what is",
            "define",
            "when did",
            "how much is",
            "convert",
            "what year",
            "who is the current",
        )
        complex_markers = (
            "compare",
            "research",
            "analyze",
            "design",
            "why does",
            "evaluate",
            "trade-off",
            "architecture",
        )

        if any(text.startswith(m) for m in trivial_markers) and word_count < 12:
            return Complexity.TRIVIAL
        if any(m in text for m in complex_markers) or word_count > 40:
            return Complexity.COMPLEX
        return Complexity.MODERATE

    def needs_tool(self, request_text: str) -> bool:
        text = request_text.lower()
        tool_markers = (
            "current",
            "latest",
            "today",
            "search",
            "look up",
            "price of",
            "weather",
            "news",
            "who is the",
        )
        return any(m in text for m in tool_markers)

    def evaluate(self, request_text: str, *, memory_hit: bool = False) -> WasteReport:
        h = self._hash(request_text)
        seen_count = self._seen.get(h, 0)
        self._seen[h] = seen_count + 1

        report = WasteReport(
            duplicate_of_recent=seen_count > 0,
            likely_in_memory=memory_hit,
            complexity=self.classify_complexity(request_text),
            needs_tool=self.needs_tool(request_text),
            previously_failed=h in self._failed_hashes,
            recommend_skill_extraction=seen_count >= 3,
        )

        if report.duplicate_of_recent:
            report.notes.append(
                "Seen this exact request before this session — check memory before recomputing."
            )
        if report.previously_failed:
            report.notes.append(
                "A prior attempt at this failed — do not repeat the same approach unmodified."
            )
        if report.recommend_skill_extraction:
            report.notes.append(
                "Requested 3+ times — consider promoting this to a reusable Skill."
            )

        return report
