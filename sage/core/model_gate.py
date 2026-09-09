"""Model gate — approval-gated model discovery→download, mirroring the Evolver
propose/apply split (``sage/evolver/service.py``):

    ModelProposalService     — stores discovered candidates. ZERO side
                               effects: no downloads, no registry writes.
    ModelApplicationService  — the ONLY class allowed to trigger a download,
                               and only when EVERY check passes:
                                 (a) explicit ``approved=True``
                                 (b) LIVE hardware re-check (never trusts the
                                     discovery-time fit)
                                 (c) immutable audit record written BEFORE the
                                     download and another AFTER completion
                                 (d) download goes through an injected
                                     ``DownloadFn`` (no network code here)
                                 (e) on success the ModelCard is registered
                                     into the real ModelRegistry via add()
                                 (f) on failure: proposal stays 'candidate',
                                     nothing registered, failure audited

CRITICAL SAFETY RULE: NOTHING here downloads or installs automatically.
Discovery produces proposals; a human must explicitly approve (``approved=True``)
before the injectable download path is ever invoked. There is no code path
that pulls model weights without first passing this gate.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sage.audit.logger import AuditLogger
from sage.core.hardware_profiler import HardwareProfile, detect
from sage.core.model_discovery import ModelProposal, fits_hardware
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event
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
from sage.models.registry import ModelRegistry

log = get_logger(__name__)


@dataclass(frozen=True)
class DownloadResult:
    """Outcome of the injected download callable."""

    success: bool
    error: str | None = None
    final_size_gb: float | None = None
    checksum: str | None = None
    local_path: str | None = None


#: Injected download contract — wire the real HuggingFace/Ollama client here.
DownloadFn = Callable[[ModelCard, HardwareProfile], Awaitable[DownloadResult]]


# -- ModelCard <-> JSON (round-trip for persistence) ---------------------------


def _card_to_dict(card: ModelCard) -> dict[str, Any]:
    """Serialize a ModelCard to a JSON-safe dict (enums -> .value)."""
    return {
        "identity": {
            "name": card.identity.name,
            "provider": card.identity.provider,
            "version": card.identity.version,
            "source": card.identity.source,
        },
        "architecture": {
            "family": card.architecture.family,
            "param_count_b": card.architecture.param_count_b,
            "style": card.architecture.style,
        },
        "capabilities": {
            "chat": card.capabilities.chat,
            "code": card.capabilities.code,
            "vision": card.capabilities.vision,
            "long_document": card.capabilities.long_document,
            "structured_output": card.capabilities.structured_output,
            "multilingual": card.capabilities.multilingual,
        },
        "reasoning": card.reasoning.value,
        "tool_use": card.tool_use.value,
        "context_window_tokens": card.context_window_tokens,
        "memory_requirements": {
            "min_vram_gb": card.memory_requirements.min_vram_gb,
            "min_ram_gb": card.memory_requirements.min_ram_gb,
            "notes": card.memory_requirements.notes,
        },
        "quantization_supported": list(card.quantization_supported),
        "runtime_compatibility": [r.value for r in card.runtime_compatibility],
        "api_interface": card.api_interface,
        "license": card.license,
        "strengths": list(card.strengths),
        "weaknesses": list(card.weaknesses),
        "cost": {
            "input_per_million_tokens_usd": card.cost.input_per_million_tokens_usd,
            "output_per_million_tokens_usd": card.cost.output_per_million_tokens_usd,
            "local_compute_notes": card.cost.local_compute_notes,
        },
        "reliability": {
            "uptime_notes": card.reliability.uptime_notes,
            "known_failure_modes": list(card.reliability.known_failure_modes),
            "consistency": card.reliability.consistency,
        },
    }


def _card_from_dict(data: dict[str, Any]) -> ModelCard:
    """Rebuild a ModelCard from :func:`_card_to_dict` output."""
    identity = data["identity"]
    architecture = data["architecture"]
    capabilities = data["capabilities"]
    memory = data["memory_requirements"]
    cost = data["cost"]
    reliability = data["reliability"]
    return ModelCard(
        identity=Identity(
            name=identity["name"],
            provider=identity["provider"],
            version=identity["version"],
            source=identity.get("source", "huggingface"),
        ),
        architecture=Architecture(
            family=architecture["family"],
            param_count_b=architecture["param_count_b"],
            style=architecture["style"],
        ),
        capabilities=Capabilities(**capabilities),
        reasoning=ReasoningLevel(data["reasoning"]),
        tool_use=ToolUseSupport(data["tool_use"]),
        context_window_tokens=int(data["context_window_tokens"]),
        memory_requirements=MemoryRequirements(**memory),
        quantization_supported=list(data["quantization_supported"]),
        runtime_compatibility=[RuntimeTarget(v) for v in data["runtime_compatibility"]],
        api_interface=data["api_interface"],
        license=data["license"],
        strengths=list(data["strengths"]),
        weaknesses=list(data["weaknesses"]),
        cost=Cost(**cost),
        reliability=Reliability(**reliability),
    )


class ModelProposalRepository(BaseRepository):
    """Data access layer for model proposals (mirrors EvolverRepository)."""

    def __init__(self, db: Database) -> None:
        super().__init__(db)

    async def ensure_table(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS model_proposals (
                proposal_id TEXT PRIMARY KEY,
                card_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                hardware_fit_notes TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                discovered_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'candidate'
            )
            """
        )

    async def insert(self, proposal: ModelProposal) -> None:
        await self.db.execute(
            """
            INSERT INTO model_proposals (
                proposal_id, card_json, reason, hardware_fit_notes,
                source_url, discovered_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal.proposal_id,
                self.dumps(_card_to_dict(proposal.model_card)),
                proposal.reason,
                proposal.hardware_fit_notes,
                proposal.source_url,
                proposal.discovered_at.isoformat(),
                proposal.status,
            ),
        )

    async def get(self, proposal_id: str) -> ModelProposal | None:
        row = await self.db.fetchone(
            "SELECT * FROM model_proposals WHERE proposal_id = ?",
            (proposal_id,),
        )
        if row is None:
            return None
        return self._row_to_proposal(row)

    async def list_all(self, *, limit: int = 50) -> list[ModelProposal]:
        rows = await self.db.fetchall(
            "SELECT * FROM model_proposals ORDER BY discovered_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_proposal(r) for r in rows]

    def _row_to_proposal(self, row: Any) -> ModelProposal:
        return ModelProposal(
            proposal_id=row["proposal_id"],
            model_card=_card_from_dict(self.loads(row["card_json"])),
            reason=row["reason"],
            hardware_fit_notes=row["hardware_fit_notes"],
            source_url=row["source_url"],
            discovered_at=datetime.fromisoformat(row["discovered_at"]),
            status="candidate",
        )


class ModelProposalService:
    """Isolated service dedicated strictly to storing discovered proposals.

    Safety Guarantee:
    - ZERO side effects: no downloads, no registry writes, no routing
      changes. Only persists candidates.
    - Rejects anything that is not status='candidate' — discovery's output
      invariant enforced at the storage boundary.
    """

    def __init__(
        self,
        repo: ModelProposalRepository,
        events: EventBus | None = None,
    ) -> None:
        self._repo = repo
        self._events = events

    async def propose(self, proposal: ModelProposal) -> ModelProposal:
        if proposal.status != "candidate":
            raise ValueError(
                f"ModelProposalService only stores candidates, got "
                f"{proposal.status!r} for {proposal.proposal_id}."
            )
        await self._repo.insert(proposal)
        log.info(
            "model_gate.proposed",
            id=proposal.proposal_id,
            name=proposal.model_card.identity.name,
        )
        if self._events:
            await self._events.publish(
                Event(
                    type="model.proposal_created",
                    payload={
                        "proposal_id": proposal.proposal_id,
                        "name": proposal.model_card.identity.name,
                    },
                    source="model_gate",
                )
            )
        return proposal

    async def get(self, proposal_id: str) -> ModelProposal | None:
        return await self._repo.get(proposal_id)

    async def list_proposals(self, *, limit: int = 50) -> list[ModelProposal]:
        return await self._repo.list_all(limit=limit)


class ModelApplicationService:
    """The ONLY class allowed to trigger a model download.

    Mirrors Evolver's ApplicationService: explicit ``approved=True``,
    LIVE hardware re-check, audit BEFORE and AFTER, download only via the
    injected ``DownloadFn``, registration via ``ModelRegistry.add()`` on
    success, and candidate/failure stays audited on failure.
    """

    def __init__(
        self,
        repo: ModelProposalRepository,
        audit: AuditLogger,
        registry: ModelRegistry,
        download: DownloadFn | None = None,
        *,
        hardware_provider: Callable[[], HardwareProfile] = detect,
        events: EventBus | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._registry = registry
        #: Default to the real HF/Ollama downloader (providers package); the
        #: gate never re-decides approval/hardware — it only executes the pull.
        if download is None:
            from sage.core.providers.model_download import default_downloader

            download = default_downloader
        self._download = download
        self._hardware_provider = hardware_provider
        self._events = events

    async def apply(
        self,
        proposal_id: str,
        *,
        approved: bool,
        approver: str = "user",
        reason: str | None = None,
    ) -> ModelProposal:
        """Approve and (only then) download + register ``proposal_id``."""
        # (a) Explicit approval — mirror Evolver's gate verbatim.
        if not approved:
            raise PermissionError(
                f"Model proposal {proposal_id} cannot be applied: "
                "explicit approval flag is False."
            )

        proposal = await self._repo.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Model proposal not found: {proposal_id}")

        name = proposal.model_card.identity.name

        # (b) LIVE hardware re-check — never trust the discovery-time fit.
        hardware = self._hardware_provider()
        reject = fits_hardware(proposal.model_card, hardware)
        if reject is not None:
            await self._record(
                subject_id=proposal_id,
                principal=approver,
                status="failed",
                summary=f"Model download refused — hardware re-check failed: {name}",
                reasoning=f"{reason or 'no reason provided'}; {reject}",
                detail={
                    "proposal_id": proposal_id,
                    "model_name": name,
                    "hardware_reason": reject,
                    "gpu_available": hardware.gpu_available,
                    "vram_gb": hardware.vram_gb,
                    "ram_gb": hardware.ram_gb,
                },
            )
            raise ValueError(
                f"Model {name} fails hardware re-check: {reject}"
            )

        # (c) Audit BEFORE the download starts.
        await self._record(
            subject_id=proposal_id,
            principal=approver,
            status="ok",
            summary=f"Model download approved and starting: {name}",
            reasoning=reason or "human-approved via model gate",
            detail={
                "proposal_id": proposal_id,
                "model_name": name,
                "source_url": proposal.source_url,
                "gpu_available": hardware.gpu_available,
                "vram_gb": hardware.vram_gb,
                "ram_gb": hardware.ram_gb,
            },
        )

        # (d) Download via the injected DownloadFn.
        result: DownloadResult
        try:
            result = await self._download(proposal.model_card, hardware)
        except Exception as exc:  # noqa: BLE001 — audit, never crash the loop.
            log.exception("model_gate.download_exception", proposal_id=proposal_id)
            await self._record(
                subject_id=proposal_id,
                principal=approver,
                status="failed",
                summary=f"Model download failed (exception): {name}",
                reasoning=str(exc),
                detail={"proposal_id": proposal_id, "model_name": name},
            )
            return proposal  # stays candidate

        if not result.success:
            await self._record(
                subject_id=proposal_id,
                principal=approver,
                status="failed",
                summary=f"Model download failed: {name}",
                reasoning=result.error or "unknown download error",
                detail={
                    "proposal_id": proposal_id,
                    "model_name": name,
                    "error": result.error,
                },
            )
            log.warning(
                "model_gate.download_failed",
                proposal_id=proposal_id,
                name=name,
                error=result.error,
            )
            return proposal  # stays candidate

        # (e) Register into the real ModelRegistry — reuse existing add().
        try:
            self._registry.add(proposal.model_card)
        except Exception as exc:  # noqa: BLE001
            log.exception("model_gate.register_failed", proposal_id=proposal_id)
            await self._record(
                subject_id=proposal_id,
                principal=approver,
                status="failed",
                summary=f"Model downloaded but registration failed: {name}",
                reasoning=str(exc),
                detail={"proposal_id": proposal_id, "model_name": name},
            )
            return proposal

        # (c') Audit AFTER completion, including download artifacts.
        await self._record(
            subject_id=proposal_id,
            principal=approver,
            status="ok",
            summary=f"Model download completed and registered: {name}",
            reasoning=reason or "human-approved via model gate",
            detail={
                "proposal_id": proposal_id,
                "model_name": name,
                "final_size_gb": result.final_size_gb,
                "checksum": result.checksum,
                "local_path": result.local_path,
            },
        )
        log.info(
            "model_gate.applied",
            proposal_id=proposal_id,
            name=name,
            approver=approver,
        )
        if self._events:
            await self._events.publish(
                Event(
                    type="model.model_applied",
                    payload={
                        "proposal_id": proposal_id,
                        "name": name,
                        "approver": approver,
                    },
                    source="model_gate",
                )
            )
        return proposal

    async def retire(
        self,
        model_name: str,
        *,
        approver: str = "user",
        reason: str | None = None,
    ) -> ModelCard:
        """Remove a model from active routing (mirror Evolver's retire).

        Does NOT delete files — it only stops the model from being routed to
        by removing its card from ModelRegistry, and writes an audit entry.
        """
        card = next(
            (c for c in self._registry.all() if c.identity.name == model_name),
            None,
        )
        if card is None:
            raise KeyError(f"Model not registered: {model_name}")

        self._registry.cards = [
            c for c in self._registry.cards if c.identity.name != model_name
        ]
        await self._record(
            subject_id=model_name,
            principal=approver,
            status="ok",
            summary=f"Model retired from active routing: {model_name}",
            reasoning=reason or "retired via model gate",
            detail={"model_name": model_name, "provider": card.identity.provider},
        )
        log.info(
            "model_gate.retired",
            name=model_name,
            approver=approver,
        )
        return card

    async def _record(
        self,
        *,
        subject_id: str,
        principal: str,
        status: str,
        summary: str,
        reasoning: str,
        detail: dict[str, Any],
    ) -> None:
        """One append-only audit entry for this gate (kind='approval')."""
        await self._audit.record(
            kind="approval",
            subject_id=subject_id,
            principal=principal,
            status=status,
            summary=summary,
            reasoning=reasoning,
            approvals=[principal],
            detail=detail,
        )
