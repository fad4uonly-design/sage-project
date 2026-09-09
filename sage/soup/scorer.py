"""SOUP scorer implementations — deterministic offline evaluation."""

from __future__ import annotations

import re
from typing import Callable

from sage.soup.models import EvalCase

# Offline scorer type: (response, case) -> score (0-100)
CaseScorer = Callable[[str, EvalCase], int]

STOP_WORDS = {
    "the", "and", "for", "that", "this", "with", "from", "you", "are", "was",
    "has", "can", "will", "do", "did", "is", "in", "on", "at", "to", "a", "an",
    "of", "it", "my", "me", "i", "we", "our", "your",
}


def tokenize(text: str) -> list[str]:
    """Tokenize text into filtered keyword tokens (lowercase, no stop words, min 3 chars)."""
    normalized = text.lower()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    tokens = [word for word in normalized.split() if len(word) >= 3 and word not in STOP_WORDS]
    return tokens


def keyword_overlap_scorer(response: str, test_case: EvalCase) -> int:
    """Deterministic offline scorer: keyword coverage of the expected answer.

    Without an expected answer, falls back to output sanity check (non-empty,
    lexical diversity) so a comparison still ranks variants by output quality.

    Returns:
        Score 0-100.
    """
    trimmed = response.strip()
    if not trimmed:
        return 0

    # No expected answer: sanity check mode
    if test_case.expected is None or not test_case.expected.strip():
        words = tokenize(trimmed)
        if len(words) == 0:
            return 25
        unique_ratio = len(set(words)) / len(words)
        return min(100, round(50 + 50 * unique_ratio))

    # Expected answer provided: keyword overlap
    expected_keywords = list(set(tokenize(test_case.expected)))
    if len(expected_keywords) == 0:
        return 50 if trimmed else 0

    haystack = set(tokenize(trimmed))
    covered = sum(1 for kw in expected_keywords if kw in haystack)
    return round((covered / len(expected_keywords)) * 100)


def clamp_score(value: float) -> int:
    """Clamp score to valid 0-100 integer range."""
    if not (isinstance(value, (int, float)) and -1e10 < value < 1e10):
        return 0
    return max(0, min(100, round(value)))
