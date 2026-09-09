"""WebLearner — RAG-to-memory pipeline: search the web, learn once, remember.

Phase 1 of the self-learning roadmap. Flow of ``learn(topic)``:

  1. MEMORY FIRST — if the memory adapter already knows something similar
     (``MemoryInterface.has_similar()`` / ``lookup()``, one shared code
     path), return it. SAGE does not relearn what it knows.
  2. SEARCH — call the injected ``searcher`` (async). This class performs
     NO network I/O itself; by default it uses the DuckDuckGo provider
     (``sage.core.providers.duckduckgo_search.search_webresults``), which
     the caller can override by injecting a custom ``SearchFn``.
  3. SUMMARIZE — the injected ``summarizer`` condenses the top results into
     one concise paragraph (no model is hardcoded — any async callable).
  4. REMEMBER — the summary is persisted through ``MemoryInterface.write()``
     tagged as self-learned: pass a ``WebLearnedMemory`` (a MemoryInterface
     whose writes carry ``source="web_learned"``) so learned content stays
     distinguishable from user-provided memory.
  5. RETURN — a ``LearnedSummary`` with the topic, summary, source list, and
     timestamp.

Contracts (dependency-injected, both async like the rest of SAGE):

    SearchFn    = Callable[[str], Awaitable[Sequence[WebResult]]]
    SummarizeFn = Callable[[str, Sequence[WebResult]], Awaitable[str]]

Failure policy: nothing is written to memory unless there are usable
results AND a non-empty summary — a failed learn leaves no trace, so the
next attempt will genuinely retry instead of trusting a cached failure.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sage.logging import get_logger
from sage.memory.index import VectorIndex
from sage.memory.memory_interface import MemoryHit, MemoryInterface
from sage.memory.models import MemoryItem, MemoryType
from sage.memory.service import SQLiteMemorySystem
from sage.utils.time import utcnow

log = get_logger(__name__)

#: Source stamp for self-learned content (stored on MemoryItem.source).
WEB_LEARNED_SOURCE = "web_learned"


@dataclass(frozen=True)
class WebResult:
    """One search hit: where it came from and the raw text retrieved."""

    source: str
    content: str


class WebLearnedMemory(MemoryInterface):
    """MemoryInterface whose writes are stamped as self-learned content.

    Retrieval is inherited unchanged — same similarity machinery, same
    threshold, same single code path. Only ``write()`` is overridden so
    items written by the WebLearner carry ``source="web_learned"`` (plus
    ``via="web_learner"`` metadata), keeping them distinguishable from
    user-provided memory. Self-learned items default to a lower item
    confidence (0.75) and ``MemoryType.SEMANTIC`` — they are derived
    knowledge, not user testimony.
    """

    def __init__(
        self,
        system: SQLiteMemorySystem,
        index: VectorIndex,
        *,
        source_tag: str = WEB_LEARNED_SOURCE,
        memory_type: MemoryType = MemoryType.SEMANTIC,
        **kwargs: Any,
    ) -> None:
        super().__init__(system, index, memory_type=memory_type, **kwargs)
        self._source_tag = source_tag

    async def write(self, request_text: str, value: str) -> None:
        """Persist request -> value, stamped as self-learned web knowledge."""
        request = request_text.strip()
        answer = value.strip()
        if not request or not answer:
            raise ValueError("WebLearnedMemory.write needs non-empty request and value.")
        content = f"{request} {answer}"
        item = MemoryItem(
            type=self._memory_type,
            content=content,
            summary=answer,
            source=self._source_tag,
            confidence=0.75,
            metadata={"lean_request": request, "via": "web_learner", "learned_from": "web"},
        )
        memory_id = await self._system.store(item)
        await self._sync_vector(memory_id, content)


def _usable_results(results: Sequence[WebResult], cap: int) -> list[WebResult]:
    """Drop empty hits, dedupe by source (first wins), cap the count."""
    seen: set[str] = set()
    usable: list[WebResult] = []
    for result in results:
        if not result.content.strip() or result.source in seen:
            continue
        seen.add(result.source)
        usable.append(result)
        if len(usable) >= cap:
            break
    return usable


class WebLearner:
    """Learns a topic from the web once, then serves it from memory.

    Args:
        memory: any ``MemoryInterface``; pass a ``WebLearnedMemory`` so
            writes are tagged ``source="web_learned"``.
        searcher: async ``(topic) -> Sequence[WebResult]`` (no I/O happens
            in this class — the provider is wired in here).
        summarizer: async ``(topic, results) -> str`` (any model/backend).
        max_results: how many deduped, non-empty results are handed to the
            summarizer.
    """

    def __init__(
        self,
        memory: MemoryInterface,
        searcher: SearchFn | None = None,
        summarizer: SummarizeFn | None = None,
        *,
        max_results: int = 5,
    ) -> None:
        if max_results < 1:
            raise ValueError("max_results must be >= 1")
        self._memory = memory
        chosen_searcher: SearchFn | None = (
            searcher if searcher is not None else DEFAULT_SEARCHER
        )
        if chosen_searcher is None:
            raise RuntimeError(
                "WebLearner needs a searcher — install 'duckduckgo-search' "
                "or pass a custom SearchFn explicitly."
            )
        self._searcher = chosen_searcher
        self._summarizer = (
            summarizer if summarizer is not None else DEFAULT_SUMMARIZER
        )
        self._max_results = max_results

    async def learn(self, topic: str) -> LearnedSummary:
        """Learn ``topic`` unless memory already knows something similar."""
        query = topic.strip()
        if not query:
            raise ValueError("WebLearner.learn needs a non-empty topic.")

        # 1. MEMORY FIRST (has_similar() and lookup() share one code path;
        # gate on the boolean, then fetch the hit to serve it).
        if await self._memory.has_similar(query):
            hit: MemoryHit | None = await self._memory.lookup(query)
            if hit is not None:
                log.debug("web_learner.served_from_memory", topic=query, key=hit.key)
                return LearnedSummary(
                    topic=query,
                    summary=hit.value,
                    sources=[f"memory:{hit.key}"],
                    learned_at=utcnow(),
                )

        # 2. SEARCH
        results = await self._searcher(query)

        # 3. SUMMARIZE (only usable, deduped, capped results)
        usable = _usable_results(results, self._max_results)
        if not usable:
            raise WebLearnError(f"no usable search results for topic: {query!r}")
        summary = (await self._summarizer(query, usable)).strip()
        if not summary:
            raise WebLearnError(f"summarizer produced an empty summary for topic: {query!r}")

        # 4. REMEMBER (tagged by the memory adapter) + 5. RETURN
        await self._memory.write(query, summary)
        log.info(
            "web_learner.learned",
            topic=query,
            sources=len(usable),
            summary_chars=len(summary),
        )
        return LearnedSummary(
            topic=query,
            summary=summary,
            sources=[result.source for result in usable],
            learned_at=utcnow(),
        )



@dataclass(frozen=True)
class LearnedSummary:
    """The outcome of a learn() call."""

    topic: str
    summary: str
    sources: list[str] = field(default_factory=list)
    learned_at: datetime = field(default_factory=utcnow)


class WebLearnError(RuntimeError):
    """Raised when nothing usable was learned (no results / empty summary)."""


#: Async search contract — the default searcher slot is wired to the real
#: DuckDuckGo provider below; inject your own to override it.
SearchFn = Callable[[str], Awaitable[Sequence[WebResult]]]
#: Async summarizer contract — topic + top results -> concise summary text.
SummarizeFn = Callable[[str, Sequence[WebResult]], Awaitable[str]]

try:  # provider wiring (additive): real DuckDuckGo search, no API key.
    from sage.core.providers.duckduckgo_search import search_webresults as _default_searcher
    DEFAULT_SEARCHER: SearchFn | None = _default_searcher
except ImportError:  # provider package unavailable — the slot stays injectable
    DEFAULT_SEARCHER = None


class _BlockedSummarizer:
    """Default ``SummarizeFn`` — deliberately BLOCKED, never fake.

    SAGE's model registry is placeholder-only (no live callable model
    runtime is wired end-to-end), so SAGE will not pretend to summarize.
    Calling ``learn()`` without an injected summarizer raises a clear
    ``WebLearnError`` pointing at the missing runtime.
    """

    async def __call__(self, topic: str, results: Sequence[WebResult]) -> str:
        raise WebLearnError(
            "no live model endpoint configured — SummarizeFn requires a real "
            "model runtime to be wired first; inject one explicitly."
        )


DEFAULT_SUMMARIZER: SummarizeFn = _BlockedSummarizer()
