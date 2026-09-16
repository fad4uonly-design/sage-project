"""Tests for the DuckDuckGo search provider + default-searcher wiring.

No real network access anywhere: ``ddgs.DDGS`` is
monkeypatched with an in-memory double returning recorded-style fixtures,
and the region-backoff behavior is exercised by making the fake fail on
specific regions.
"""

from __future__ import annotations

from collections.abc import Sequence

import ddgs
import pytest
from sage.core.model_discovery import ModelDiscoverer, ModelMetadata
from sage.core.providers.duckduckgo_search import (
    search,
    search_discovery,
    search_webresults,
)
from sage.core.web_learner import WebLearner, WebLearnError, WebResult

# Recorded-style DDG payloads (keys match DDGS.text() output: title/href/body).
RAW = [
    {
        "title": "Rust Programming Language",
        "href": "https://rust-lang.org",
        "body": "Official home of the Rust programming language.",
    },
    {
        "title": "A Gentle Intro to Rust",
        "href": "https://guide.example/rust",
        "body": "Friendly first steps with Rust.",
    },
]


class FakeDDGS:
    """In-memory double for ``ddgs.DDGS``.

    ``fail_regions`` makes ``text()`` raise for specific regions so tests can
    exercise the provider's region backoff without touching the network.
    """

    def __init__(
        self,
        rows: Sequence[dict[str, str]],
        fail_regions: set[str | None] | None = None,
    ) -> None:
        self.rows = list(rows)
        self.fail_regions = set(fail_regions or ())
        self.calls: list[tuple[str, str | None, int | None]] = []

    def text(
        self,
        keywords: str,
        region: str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, str]]:
        self.calls.append((keywords, region, max_results))
        if region in self.fail_regions:
            raise RuntimeError(f"rate limited for {region!r}")
        return list(self.rows)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeDDGS:
    instance = FakeDDGS(RAW)

    def _factory() -> FakeDDGS:
        return instance

    monkeypatch.setattr(ddgs, "DDGS", _factory)
    return instance


class RecordingMemory:
    """Minimal MemoryInterface double (no persistence)."""

    async def has_similar(self, request_text: str) -> bool:
        return False

    async def lookup(self, request_text: str) -> None:
        return None

    async def write(self, request_text: str, value: str) -> None:
        return None


async def test_search_ddg_returns_shared_engine_results(fake: FakeDDGS) -> None:
    out = await search("rust")
    assert [r.title for r in out] == [
        "Rust Programming Language",
        "A Gentle Intro to Rust",
    ]
    assert out[0].url == "https://rust-lang.org"
    assert out[0].snippet == "Official home of the Rust programming language."


async def test_search_webresults_projects_to_webresult(fake: FakeDDGS) -> None:
    out = await search_webresults("rust")
    assert len(out) == 2
    assert isinstance(out[0], WebResult)
    assert out[0].source == "https://rust-lang.org"
    assert out[0].content == "Official home of the Rust programming language."


async def test_search_discovery_projects_to_model_metadata(fake: FakeDDGS) -> None:
    out = await search_discovery("rust")
    assert len(out) == 2
    assert isinstance(out[0], ModelMetadata)
    assert out[0].name == "Rust Programming Language"
    assert out[0].provider == "duckduckgo"
    assert out[0].source_url == "https://rust-lang.org"


async def test_no_results_returns_empty(fake: FakeDDGS) -> None:
    fake.rows = []
    assert await search_webresults("rust") == ()
    assert await search_discovery("rust") == ()


async def test_region_backoff_retries_after_first_region_fails(fake: FakeDDGS) -> None:
    fake.fail_regions = {"us-en"}
    out = await search("rust")
    assert len(out) == 2  # recovered on the second region
    regions = [call[1] for call in fake.calls]
    assert "us-en" in regions and "en-US" in regions


async def test_all_regions_failing_returns_empty_not_exception(fake: FakeDDGS) -> None:
    fake.fail_regions = {"us-en", "en-US", None}
    assert await search("rust") == ()
    assert len(fake.calls) >= 3  # every region was attempted


async def test_empty_query_never_raises(fake: FakeDDGS) -> None:
    assert await search("") == ()
    assert await search("   ") == ()
    assert await search_webresults("") == ()


async def test_max_results_respected(fake: FakeDDGS) -> None:
    out = await search("rust", max_results=1)
    assert len(out) == 1
    assert out[0].title == "Rust Programming Language"


def test_web_learner_default_searcher_is_the_provider() -> None:
    learner = WebLearner(RecordingMemory())
    assert learner._searcher is search_webresults


def test_model_discoverer_default_searcher_is_the_provider() -> None:
    discoverer = ModelDiscoverer()
    assert discoverer._searcher is search_discovery


async def test_default_summarizer_is_blocked_not_fake() -> None:
    learner = WebLearner(RecordingMemory())
    with pytest.raises(WebLearnError):
        await learner._summarizer("rust", [])
