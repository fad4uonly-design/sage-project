"""DuckDuckGo-style web search provider for SAGE.

Wires real async ``SearchFn`` implementations (no API key) into both
WebLearner (``sage/core/web_learner.py``) and ModelDiscoverer
(``sage/core/model_discovery.py``). Uses the maintained
``duckduckgo-search`` package (pinned in ``pyproject.toml``) rather than
hand-rolled scraping, for reliability.

Result shape from ``DDGS.text()`` (observed at runtime)::

    { "title": str, "href": str, "body": str }

One search engine (``search()``) + two thin adapters:

* ``search_webresults(query) -> Sequence[WebResult]``   — WebLearner's
  ``SearchFn`` contract (source=url, content=snippet).
* ``search_discovery(query) -> Sequence[ModelMetadata]`` — ModelDiscoverer's
  ``SearchFn`` contract (source_url=url).

Failure policy (mirrors WebLearner's existing contract): no results /
rate-limited / network error -> return ``[]``, never raise. WebLearner
already turns "no usable results" into ``WebLearnError`` and writes
nothing, so a completely failed search leaves no trace.

Tests must NOT hit the real network — they monkeypatch ``DDGS.text``
with recorded fixtures.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sage.logging import get_logger

if TYPE_CHECKING:
    from sage.core.model_discovery import ModelMetadata
    from sage.core.web_learner import WebResult

log = get_logger(__name__)

_DDGS_TEXT_MAX_RESULTS_DEFAULT = 10
_DDGS_REGION_BACKOFF = ("us-en", "en-US", None)


@dataclass(frozen=True)
class SearchResult:
    """One DuckDuckGo hit — the shared shape both adapters project from."""

    title: str
    url: str
    snippet: str


def _import_ddgs() -> Any:
    """Return a ``duckduckgo_search.DDGS`` client instance.

    The import is deferred to call time so SAGE imports cleanly when the
    optional provider package is absent; the default-searcher wiring slots
    degrade to a clear runtime error instead of a module-import failure.
    """
    import duckduckgo_search

    ddgs = duckduckgo_search.DDGS()
    if not hasattr(ddgs, "text") or not callable(ddgs.text):
        raise RuntimeError("duckduckgo_search.DDGS.text missing")
    return ddgs


def _run_ddg_text(query: str, max_results: int) -> list[dict[str, str]]:
    """Synchronous DDG text search with region backoff.

    Returns ``list[dict[str, str]]`` of ``{title, href, body}`` (the
    documented ``DDGS.text()`` output shape); ``[]`` on any failure or when
    no region yields results.
    """
    try:
        ddgs = _import_ddgs()
    except Exception as exc:
        log.warning("ddg_import_failed", error=str(exc))
        return []

    for region in _DDGS_REGION_BACKOFF:
        try:
            res = ddgs.text(query, region=region, max_results=max_results)
        except Exception as exc:
            log.warning("ddg_call_failed", query=query[:120], region=region, error=str(exc))
            continue
        if not res:
            continue
        cleaned: list[dict[str, str]] = []
        for item in res:
            if isinstance(item, dict):
                cleaned.append({str(k): str(v) for k, v in item.items()})
        return cleaned
    return []


async def search(
    query: str,
    *,
    max_results: int = _DDGS_TEXT_MAX_RESULTS_DEFAULT,
) -> Sequence[SearchResult]:
    """Core DuckDuckGo search — one implementation, both adapters use it.

    Returns an empty sequence on any failure; never raises. Callers project
    ``SearchResult`` onto their own contract.
    """
    if not query or not query.strip():
        return ()
    try:
        raw = _run_ddg_text(query, max_results)
    except Exception as exc:
        log.warning("ddg_search.failed", query=query[:120], error=str(exc))
        return ()
    return tuple(
        SearchResult(
            title=r.get("title", "").strip(),
            url=r.get("href", "").strip(),
            snippet=r.get("body", "").strip(),
        )
        for r in raw[:max_results]
        if r.get("href")
    )


async def search_webresults(
    query: str,
    *,
    max_results: int = _DDGS_TEXT_MAX_RESULTS_DEFAULT,
) -> Sequence[WebResult]:
    """WebLearner's ``SearchFn``: ``search()`` projected onto ``WebResult``.

    ``WebResult`` is imported lazily to avoid an import cycle with
    ``sage/core/web_learner.py`` (which imports this module for
    ``DEFAULT_SEARCHER``).
    """
    from sage.core.web_learner import WebResult  # deferred: avoids import cycle

    results = await search(query, max_results=max_results)
    return tuple(
        WebResult(source=r.url, content=r.snippet)
        for r in results
        if r.url and r.snippet
    )


async def search_discovery(
    query: str,
    *,
    max_results: int = _DDGS_TEXT_MAX_RESULTS_DEFAULT,
) -> Sequence[ModelMetadata]:
    """ModelDiscoverer's ``SearchFn``: ``search()`` projected onto ``ModelMetadata``.

    A web hit cannot honestly fill every ``ModelMetadata`` field (param
    count, VRAM, license, ...), so only the fields a web result genuinely
    carries are set: ``name`` (page title or url), ``provider``
    (``"duckduckgo"``) and ``source_url``. ``_card_from_metadata`` in
    ``model_discovery.py`` fills the rest from defaults. ``ModelMetadata``
    is imported lazily to avoid an import cycle with ``model_discovery.py``.
    """
    from sage.core.model_discovery import ModelMetadata  # deferred: avoids import cycle

    results = await search(query, max_results=max_results)
    return tuple(
        ModelMetadata(
            name=r.title.strip() or r.url,
            provider="duckduckgo",
            source_url=r.url,
        )
        for r in results
        if r.url
    )
