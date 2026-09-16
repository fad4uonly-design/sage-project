"""Model Discovery — propose candidate models that fit BOTH a stated need and
this machine's hardware.

Phase 3 of the autonomy roadmap. Discovery ONLY produces proposals. It never
downloads, installs, or registers anything: every candidate must pass the
human-approval gate (``sage/core/model_gate.py``) before any model weights are
pulled or made routable by SAGE.

Safety-critical design:
- Hardware is a HARD filter, not a soft preference: a candidate whose
  ``min_vram_gb`` / ``min_ram_gb`` exceeds the detected hardware is EXCLUDED
  entirely (never proposed, never deprioritized). ``fits_hardware()`` is the
  single source of that constraint and is shared with the approval gate so
  the gate re-checks the same way against live hardware.
- When VRAM is required but the detected amount is unknown, the model is
  excluded too — SAGE cannot verify a fit it cannot measure.
- Search is injectable (``SearchFn``, same DI pattern as WebLearner) so the
  real Hugging Face / Ollama registry provider can be wired in later without
  touching this module. No network code lives here.

The ``ModelMetadata`` dataclass is the search-seam contract: the real provider
returns these; ``ModelDiscoverer`` maps each to a full ``ModelCard`` (reusing
the exact dataclass from ``sage/models/model_card.py``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sage.core.hardware_profiler import HardwareProfile
from sage.logging import get_logger
from sage.models.model_card import (
    Architecture,
    Capabilities,
    Cost,
    Identity,
    MemoryRequirements,
    ModelCard,
    ReasoningLevel,
    Reliability,
    RuntimeTarget,
    ToolUseSupport,
)
from sage.utils.ids import new_id
from sage.utils.time import utcnow

log = get_logger(__name__)


@dataclass(frozen=True)
class ModelMetadata:
    """Metadata the search provider returns for one candidate model.

    Mirrors the ModelCard taxonomy so the discoverer can build a complete
    card from whatever the (injectable) provider supplies. Values are plain
    strings/lists on purpose — they map onto the ModelCard enums explicitly
    in ``_card_from_metadata``, and providers never touch the enums directly.
    """

    name: str
    provider: str = "unknown"
    version: str = "latest"
    family: str = "unknown"
    param_count_b: float | None = None
    capabilities: set[str] = field(default_factory=set)  # chat, code, vision, ...
    reasoning: str = "none"           # ReasoningLevel value: none|basic|cot|extended
    tool_use: str = "none"            # ToolUseSupport value: none|prompted_only|native
    context_window_tokens: int = 0
    min_vram_gb: float | None = None
    min_ram_gb: float | None = None
    quantization_supported: list[str] = field(default_factory=list)
    runtime_compatibility: list[str] = field(default_factory=list)  # RuntimeTarget values
    api_interface: str = ""
    license: str = "unknown"
    cost_input_usd_per_m: float | None = None
    cost_output_usd_per_m: float | None = None
    local_compute_notes: str = ""
    consistency: str = "unknown"
    known_failure_modes: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    source_url: str = ""


@dataclass(frozen=True)
class ModelProposal:
    """A discovered candidate awaiting human approval. Never a download."""

    proposal_id: str
    model_card: ModelCard
    reason: str                      # why this model fills the stated need
    hardware_fit_notes: str          # the verified fit, spelled out
    source_url: str                  # where the model can be pulled from
    discovered_at: datetime
    status: Literal["candidate"] = "candidate"


#: Async search contract — the default searcher slot is wired to the real
#: DuckDuckGo provider below; inject your own to override it.
SearchFn = Callable[[str], Awaitable[Sequence[ModelMetadata]]]

try:  # provider wiring (additive): DuckDuckGo search as the default source.
    from sage.core.providers.duckduckgo_search import (
        search_discovery as _default_discovery_searcher,
    )
    DEFAULT_SEARCHER: SearchFn | None = _default_discovery_searcher
except ImportError:  # provider package unavailable — the slot stays injectable
    DEFAULT_SEARCHER = None


def _card_from_metadata(meta: ModelMetadata) -> ModelCard:
    """Map search metadata onto the real ModelCard dataclass."""
    caps = meta.capabilities
    try:
        reasoning = ReasoningLevel(meta.reasoning)
    except ValueError:
        reasoning = ReasoningLevel.NONE
    try:
        tool_use = ToolUseSupport(meta.tool_use)
    except ValueError:
        tool_use = ToolUseSupport.NONE

    runtime: list[RuntimeTarget] = []
    for raw in meta.runtime_compatibility:
        try:
            runtime.append(RuntimeTarget(raw))
        except ValueError:
            log.warning("model_discovery.unknown_runtime_target", target=raw)

    return ModelCard(
        identity=Identity(name=meta.name, provider=meta.provider, version=meta.version),
        architecture=Architecture(family=meta.family, param_count_b=meta.param_count_b),
        capabilities=Capabilities(
            chat=("chat" in caps) or not caps,
            code="code" in caps,
            vision="vision" in caps,
            long_document="long_document" in caps,
            structured_output="structured_output" in caps,
            multilingual="multilingual" in caps,
        ),
        reasoning=reasoning,
        tool_use=tool_use,
        context_window_tokens=meta.context_window_tokens,
        memory_requirements=MemoryRequirements(
            min_vram_gb=meta.min_vram_gb,
            min_ram_gb=meta.min_ram_gb,
            notes="from discovery metadata",
        ),
        quantization_supported=list(meta.quantization_supported),
        runtime_compatibility=runtime or [RuntimeTarget.API_ONLY],
        api_interface=meta.api_interface,
        license=meta.license,
        strengths=list(meta.strengths),
        weaknesses=list(meta.weaknesses),
        cost=Cost(
            input_per_million_tokens_usd=meta.cost_input_usd_per_m,
            output_per_million_tokens_usd=meta.cost_output_usd_per_m,
            local_compute_notes=meta.local_compute_notes,
        ),
        reliability=Reliability(
            consistency=meta.consistency,
            known_failure_modes=list(meta.known_failure_modes),
        ),
    )


def fits_hardware(card: ModelCard, hardware: HardwareProfile) -> str | None:
    """Return a reason why ``card`` does NOT fit ``hardware``, or ``None`` if
    it fits. This is the HARD filter — shared by discovery and the approval
    gate's live re-check so both use the exact same constraint.

    Rules:
    - A model requiring VRAM is excluded when no GPU is detected, when the
      detected VRAM is unknown (cannot verify a fit), or when detected VRAM
      is below the requirement.
    - A model whose min_ram exceeds detected RAM is excluded.
    """
    req = card.memory_requirements
    if req.min_vram_gb and req.min_vram_gb > 0:
        if not hardware.gpu_available:
            return f"requires {req.min_vram_gb:g} GiB VRAM but no GPU was detected"
        if hardware.vram_gb is None:
            return (
                f"requires {req.min_vram_gb:g} GiB VRAM but detected VRAM is "
                "unknown — cannot verify a fit"
            )
        if hardware.vram_gb < req.min_vram_gb:
            return (
                f"requires {req.min_vram_gb:g} GiB VRAM, only "
                f"{hardware.vram_gb:g} GiB available"
            )
    if req.min_ram_gb and hardware.ram_gb < req.min_ram_gb:
        return (
            f"requires {req.min_ram_gb:g} GiB RAM, only "
            f"{hardware.ram_gb:g} GiB available"
        )
    return None


def _fit_notes(card: ModelCard, hardware: HardwareProfile) -> str:
    """Human-readable summary of the verified fit (for the proposal)."""
    req = card.memory_requirements
    parts: list[str] = []
    if req.min_vram_gb and req.min_vram_gb > 0:
        vram = f"{hardware.vram_gb:g}" if hardware.vram_gb is not None else "unknown"
        parts.append(f"VRAM {req.min_vram_gb:g} <= {vram} GiB available")
    if req.min_ram_gb:
        parts.append(f"RAM {req.min_ram_gb:g} <= {hardware.ram_gb:g} GiB available")
    return "; ".join(parts) or "no memory constraints in metadata"


def _candidate_reason(need: str, card: ModelCard) -> str:
    """Heuristic 'why this fills the need'. Honest about being heuristic:
    a real relevance classifier/LLM can replace this later without touching
    the proposal shape."""
    tokens = {t for t in need.lower().split() if len(t) > 3}
    haystack = " ".join(
        [
            card.identity.name,
            card.identity.provider,
            card.architecture.family,
            *card.strengths,
        ]
    ).lower()
    overlap = tokens & set(haystack.split())
    if overlap:
        return (
            f"Candidate for {need!r} — matches {', '.join(sorted(overlap))} "
            f"({card.identity.name})."
        )
    return f"Candidate for {need!r} from {card.identity.provider} metadata."


class ModelDiscoverer:
    """Discovers model candidates for a need, hard-filtered by hardware.

    Args:
        searcher: async ``(need) -> Sequence[ModelMetadata]``. No network
            calls happen in this class — the registry provider is wired in
            here by the caller (same DI pattern as WebLearner).
        max_results: how many search hits to consider.
    """

    def __init__(self, searcher: SearchFn | None = None, *, max_results: int = 10) -> None:
        if max_results < 1:
            raise ValueError("max_results must be >= 1")
        chosen: SearchFn | None = searcher if searcher is not None else DEFAULT_SEARCHER
        if chosen is None:
            raise RuntimeError(
                "ModelDiscoverer needs a searcher — install 'ddgs' "
                "or pass a custom SearchFn explicitly."
            )
        self._searcher = chosen
        self._max_results = max_results

    async def discover(
        self, need: str, hardware: HardwareProfile
    ) -> list[ModelProposal]:
        """Propose candidates for ``need`` that fit ``hardware``.

        Pure metadata work: search -> build ModelCard -> HARD-filter -> wrap
        in ModelProposal(status='candidate'). Never downloads anything.
        """
        query = need.strip()
        if not query:
            raise ValueError("ModelDiscoverer.discover needs a non-empty need.")

        found = await self._searcher(query)
        proposals: list[ModelProposal] = []
        for meta in found[: self._max_results]:
            card = _card_from_metadata(meta)
            reject = fits_hardware(card, hardware)
            if reject is not None:
                # HARD filter: excluded entirely, not deprioritized.
                log.info(
                    "model_discovery.filtered_out",
                    name=card.identity.name,
                    need=query,
                    reason=reject,
                )
                continue
            proposals.append(
                ModelProposal(
                    proposal_id=new_id("model"),
                    model_card=card,
                    reason=_candidate_reason(query, card),
                    hardware_fit_notes=_fit_notes(card, hardware),
                    source_url=meta.source_url,
                    discovered_at=utcnow(),
                    status="candidate",
                )
            )
        log.info(
            "model_discovery.completed",
            need=query,
            found=len(found),
            proposed=len(proposals),
        )
        return proposals
