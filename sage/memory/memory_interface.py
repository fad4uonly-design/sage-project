"""MemoryInterface — the Lean Intelligence seam over SAGE's real memory system.

This module is the plug-in point for the Lean Intelligence Value Router
(``sage/core/value_router.py`` / ``sage/core/lean_loop.py``): before any
model call the router asks ``lookup()`` whether SAGE already knows the
answer, and after a verified turn ``LeanLoop`` calls ``write()`` so the
answer becomes retrievable next time.

This is an adapter, NOT a memory implementation. All persistence goes
through the real ``SQLiteMemorySystem`` (``sage/memory/service.py``) and all
similarity search goes through the real ``SqliteVectorIndex``
(``sage/memory/index.py``) with an ``EmbeddingModel`` attached (see
``sage/models/local_embedding.py``). No existing memory code was modified
to build this — it is strictly additive.

Retrieval contract
------------------
- ``lookup()`` embeds the request text and runs exact cosine search over the
  vector index — it is NOT an exact string match. The best candidate is
  returned as a ``MemoryHit`` when its cosine score clears the
  ``similarity_threshold`` (default 0.60, see below), otherwise ``None``.
- ``write()`` persists one item through ``SQLiteMemorySystem.store()`` and
  keeps the vector index in sync via ``index.upsert()`` (public method —
  needed because the system's own vector sync only runs after ITS lazy
  embedding resolution, which an externally-attached embedding does not
  trigger). The stored content is ``"<request> <value>"`` (space-joined so
  no tokens fuse) so the request text is part of the indexed vector —
  asking about France must find "Paris."-style answers; the answer itself
  is kept in ``item.summary`` and returned verbatim as ``MemoryHit.value``.
  Duplicate writes reinforce the existing memory via the system's
  content-hash pipeline instead of duplicating rows, and the idempotent
  upsert keeps the vector correct.
- ``has_similar()`` is ``lookup(...) is not None`` — one code path, no
  duplicated similarity logic.

Similarity threshold (default 0.60)
-----------------------------------
Chosen empirically with the shipped offline ``HashingEmbeddingModel(dim=128)``,
measured through the real stack (cosine of query vs stored
``"<request> <value>"``):

    exact repeat                           ~0.87
    reworded request (e.g. contraction)    ~0.64
    heavier rewordings                     ~0.50-0.59
    same frame, different focus (e.g.
    "What is the population of France?")   ~0.66
    same topic, different question         ~0.25
    unrelated requests                     ~-0.06-0.14

0.60 separates different-topic junk (<= ~0.25) and unrelated requests from
plausibly useful hits, while exact repeats land far above it. Two honest
caveats about the offline hashing model: (a) reworded requests land in a
0.50-0.65 band, so some valid rewordings fall below 0.60 — lookups are
conservative, not exhaustive; (b) within a shared question frame the hashing
model is purely lexical, so "What is the population of France?" can
outscore a same-answer rewording. That confusion is caught by the SECOND
gate — the ValueRouter's MEMORY_ONLY confidence gate (0.9 default) — which
never short-circuits on sub-gate confidence; it only surfaces the hit as
context for the routed model. With a real embedding model (e.g.
``LocalEmbeddingModel`` + nomic-embed-text) the semantic separation returns
and both knobs behave as designed; raise the threshold to ~0.78-0.82 there.
It is a constructor argument for exactly this reason.

Known limitation: ``write()`` embeds request+answer together, so very long
stored answers dilute exact-repeat confidence (hashing space: ~0.67 for a
~30-token answer). Keep cached values concise — which is also the Lean
policy: memory stores answers, not transcripts.

Lifecycle note: production wiring (``MemoryModule``) resolves the embedding
lazily via a router resolver. This adapter does NOT depend on that
resolution — it attaches/uses the embedding itself for both lookup() and
write()'s vector upsert, and never constructs an embedding of its own.
Because both paths go through the index's single embedding slot, they are
the same instance by construction; the adapter additionally detects tag
drift (``tag_drifted``) in case the slot is later re-pointed to a different
model tag. Operational rule: use ONE embedding model per database; after a
tag change, migrate with ``system.sync_index(force=True)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sage.logging import get_logger
from sage.memory.index import VectorIndex
from sage.memory.models import MemoryItem, MemoryType
from sage.memory.service import SQLiteMemorySystem
from sage.models.interfaces import EmbeddingModel
from sage.utils.time import utcnow

log = get_logger(__name__)

DEFAULT_SIMILARITY_THRESHOLD = 0.60


@dataclass(frozen=True)
class MemoryHit:
    """A stored memory that answers the current request."""

    key: str            # memory id inside SQLiteMemorySystem
    value: str          # the stored answer
    confidence: float   # raw cosine similarity, clamped to 0-1
    age_seconds: float  # age of the memory (based on updated_at)


class MemoryInterface:
    """Adapter between the ValueRouter and SAGE's real memory system.

    Args:
        system: the real ``SQLiteMemorySystem`` to persist through and
            fetch from. Required — this adapter never keeps its own store.
        index: the vector index backing ``system`` (usually the same
            ``SqliteVectorIndex`` instance the system was built with).
        embedding: optional embedding model to attach to ``index``. Only
            pass one if the index is not already attached — attaching a
            *different* model than the one that built the vectors would
            orphan them (the index is keyed by model tag). A mismatch is
            rejected loudly rather than silently emptying search results.
        similarity_threshold: minimum cosine score for ``lookup()`` to
            return a hit. See module docstring for the measured rationale.
        memory_type: ``MemoryType`` used for items written by this adapter.
        source: ``source`` stamped on written items (audit trail).
        search_limit: how many index candidates to consider per lookup.
    """

    def __init__(
        self,
        system: SQLiteMemorySystem,
        index: VectorIndex,
        *,
        embedding: EmbeddingModel | None = None,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        memory_type: MemoryType = MemoryType.FACT,
        source: str = "lean_value_router",
        search_limit: int = 5,
    ) -> None:
        self._system = system
        self._index = index
        self._threshold = similarity_threshold
        self._memory_type = memory_type
        self._source = source
        self._search_limit = search_limit

        if embedding is not None:
            wanted = f"{embedding.provider}:{embedding.model_name}"
            if index.tag not in ("unattached", wanted):
                raise ValueError(
                    f"Index already attached to {index.tag!r}; attaching {wanted!r} "
                    "would orphan the existing vectors. Detach or reuse the "
                    "already-attached embedding model."
                )
            index.attach(embedding)
        elif index.tag == "unattached":
            log.warning(
                "lean.memory_interface.unattached_index",
                hint="embedding resolves lazily in production; lookup() returns "
                "None until an embedding model is attached",
            )

        # Drift detection baseline: the embedding slot this adapter validated.
        # The index's slot can be re-pointed later (the memory system's
        # _resolve_index attaches whatever its router resolves); vectors are
        # keyed by model tag, so a tag switch silently orphans older rows.
        self._expected_tag = index.tag
        self._tag_drifted = False

    @property
    def tag_drifted(self) -> bool:
        """True when the index's embedding slot was re-pointed to a different
        model tag after this adapter started using it."""
        return self._tag_drifted

    def _check_tag_drift(self) -> None:
        """Warn once if the embedding slot changed underneath this adapter.

        Both the adapter's ``index.upsert()``/``index.search()`` calls and the
        memory system's internal path go through the SAME single slot
        (``SqliteVectorIndex._embedding``), so within one tag the two paths
        are identical by construction. The only consistency hazard is
        temporal: a re-attach with a DIFFERENT tag makes previously written
        vectors unsearchable (they keep their old ``model_tag``)."""
        if self._tag_drifted or self._index.tag == self._expected_tag:
            return
        self._tag_drifted = True
        log.warning(
            "lean.memory_interface.tag_drift",
            expected=self._expected_tag,
            current=self._index.tag,
            hint="vectors written under the old tag are no longer searchable; "
            "rebuild via system.sync_index(force=True) and use one embedding "
            "model per database",
        )

    async def lookup(self, request_text: str) -> MemoryHit | None:
        """Best memory answering this request, or ``None`` below threshold."""
        return await self._best_hit(request_text)

    async def write(self, request_text: str, value: str) -> None:
        """Persist request -> value through the real ``SQLiteMemorySystem``."""
        request = request_text.strip()
        answer = value.strip()
        if not request or not answer:
            raise ValueError("MemoryInterface.write needs non-empty request and value.")
        content = f"{request} {answer}"
        item = MemoryItem(
            type=self._memory_type,
            content=content,
            summary=answer,
            source=self._source,
            confidence=0.9,
            metadata={"lean_request": request, "via": "memory_interface"},
        )
        memory_id = await self._system.store(item)
        await self._sync_vector(memory_id, content)

    async def _sync_vector(self, memory_id: str, content: str) -> None:
        """Guarantee the vector row for lean writes via ``index.upsert()``.

        ``SQLiteMemorySystem`` upserts vectors only after ITS embedding
        resolution has run (``_resolve_index`` via a router resolver); an
        embedding attached externally is invisible to that path. The adapter
        owns the embedding for its own lookups, so it also keeps the index in
        sync for its own writes. Upsert is idempotent per memory id, so the
        duplicate-reinforce path stays correct.
        """
        self._check_tag_drift()
        try:
            await self._index.upsert(memory_id, content)
        except RuntimeError:
            # No embedding attached yet — same degradation as lookup().
            log.debug("lean.memory_interface.upsert_without_embedding")

    async def has_similar(self, request_text: str) -> bool:
        """True when ``lookup()`` would return a hit — same code path."""
        return await self._best_hit(request_text) is not None

    async def _best_hit(self, request_text: str) -> MemoryHit | None:
        query = request_text.strip()
        if not query:
            return None
        self._check_tag_drift()
        try:
            results = await self._index.search(query, limit=self._search_limit)
        except RuntimeError:
            # Index exists but no embedding model is attached yet (lazy
            # production wiring). Degrade to "no memory hit", don't crash.
            log.debug("lean.memory_interface.search_without_embedding")
            return None

        for memory_id, score in results:
            if score < self._threshold:
                break  # results are score-descending; the rest are worse
            item = await self._system.get(memory_id)
            if item is None or item.deleted_at is not None:
                continue  # stale index entry (soft-deleted but not yet removed)
            if item.expires_at is not None and _is_expired(item.expires_at):
                continue
            return MemoryHit(
                key=memory_id,
                value=item.summary if item.summary else item.content,
                confidence=max(0.0, min(1.0, score)),
                age_seconds=_age_seconds(item),
            )
        return None


def _age_seconds(item: MemoryItem) -> float:
    stamp = item.updated_at or item.created_at
    try:
        then = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (utcnow() - then).total_seconds())


def _is_expired(expires_at: str) -> bool:
    try:
        then = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return utcnow() >= then

