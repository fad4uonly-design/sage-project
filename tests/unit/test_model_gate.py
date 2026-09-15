"""Unit tests for the model download approval gate.

Mirrors Evolver's propose/apply split. These prove the safety chain:
explicit approval required, live hardware re-check, audit-before AND
audit-after, download only via the injected DownloadFn, registration only
on success, and retire with its own audit entry. No real network anywhere.
"""

from __future__ import annotations

from pathlib import Path

from sage.audit.logger import AuditLogger
from sage.core.hardware_profiler import HardwareProfile
from sage.core.model_discovery import ModelProposal
from sage.core.model_gate import (
    DownloadResult,
    ModelApplicationService,
    ModelProposalRepository,
    ModelProposalService,
)
from sage.db.connection import Database
from sage.db.migrations import apply_migrations
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
from sage.utils.time import utcnow

PROFILED_HW = HardwareProfile(
    gpu_available=True, vram_gb=2.0, ram_gb=15.6, cpu_cores=12, free_disk_gb=282.0
)


def make_card(
    name: str = "tiny-model",
    *,
    min_vram: float = 1.0,
    min_ram: float = 4.0,
    param_count_b: float = 1.5,
) -> ModelCard:
    return ModelCard(
        identity=Identity(name=name, provider="huggingface"),
        architecture=Architecture(family="Qwen", param_count_b=param_count_b),
        capabilities=Capabilities(chat=True),
        reasoning=ReasoningLevel.BASIC,
        tool_use=ToolUseSupport.PROMPTED_ONLY,
        context_window_tokens=8192,
        memory_requirements=MemoryRequirements(min_vram_gb=min_vram, min_ram_gb=min_ram),
        quantization_supported=["int4"],
        runtime_compatibility=[RuntimeTarget.LLAMA_CPP],
        api_interface="local process",
        license="Apache 2.0",
        strengths=["fast"],
        weaknesses=["weak"],
        cost=Cost(input_per_million_tokens_usd=0.1),
        reliability=Reliability(consistency="medium"),
    )


def make_proposal(
    card: ModelCard,
    *,
    proposal_id: str = "model_test_1",
    source_url: str = "https://example/model",
) -> ModelProposal:
    return ModelProposal(
        proposal_id=proposal_id,
        model_card=card,
        reason="test proposal",
        hardware_fit_notes="ok",
        source_url=source_url,
        discovered_at=utcnow(),
        status="candidate",
    )


class FakeDownload:
    def __init__(
        self,
        result: DownloadResult | None = None,
        *,
        exc: Exception | None = None,
    ) -> None:
        self.result = result
        self.exc = exc
        self.calls: list[tuple[ModelCard, HardwareProfile]] = []

    async def __call__(self, card: ModelCard, hardware: HardwareProfile) -> DownloadResult:
        self.calls.append((card, hardware))
        if self.exc is not None:
            raise self.exc
        return self.result or DownloadResult(success=True)


async def make_stack(
    tmp_path: Path,
    *,
    download: FakeDownload | None = None,
    gateway_hw: HardwareProfile | None = None,
) -> tuple[
    ModelProposalService,
    ModelProposalRepository,
    AuditLogger,
    ModelRegistry,
    ModelApplicationService,
    Database,
    FakeDownload,
]:
    db = Database(str(tmp_path / "gate.db"))
    await db.open()
    await apply_migrations(db)

    repo = ModelProposalRepository(db)
    await repo.ensure_table()
    audit = AuditLogger(db)
    registry = ModelRegistry()
    dl = download or FakeDownload()
    target_hw = gateway_hw or PROFILED_HW
    gate = ModelApplicationService(
        repo,
        audit,
        registry,
        dl,
        hardware_provider=lambda: target_hw,
    )
    proposer = ModelProposalService(repo)
    return proposer, repo, audit, registry, gate, db, dl


# -- apply: approval gate -----------------------------------------------------


async def test_apply_without_approval_raises_permission_error(tmp_path: Path) -> None:
    proposer, repo, audit, registry, gate, db, dl = await make_stack(tmp_path)
    try:
        await proposer.propose(make_proposal(make_card()))

        try:
            await gate.apply("model_test_1", approved=False)
        except PermissionError:
            pass
        else:
            raise AssertionError("expected PermissionError when approved=False")

        assert all(c.identity.name != "tiny-model" for c in registry.all())
        assert dl.calls == [], "download must not be invoked without approval"
        assert await audit.list_recent(limit=50, kind="approval") == []
    finally:
        await db.close()


async def test_apply_with_approval_registers_and_audits_before_after(tmp_path: Path) -> None:
    dl = FakeDownload(
        DownloadResult(success=True, final_size_gb=0.9, checksum="abc123", local_path="C:/models/tiny")
    )
    proposer, repo, audit, registry, gate, db, _ = await make_stack(tmp_path, download=dl)
    try:
        await proposer.propose(make_proposal(make_card()))
        before = {c.identity.name for c in registry.all()}

        out = await gate.apply("model_test_1", approved=True, approver="tester", reason="manual check")

        assert out.status == "candidate"  # proposal record itself never transitions
        assert "tiny-model" not in before
        assert "tiny-model" in {c.identity.name for c in registry.all()}
        assert len(dl.calls) == 1
        assert dl.calls[0][0].identity.name == "tiny-model"
        assert dl.calls[0][1] is PROFILED_HW

        recs = sorted(
            (r for r in await audit.list_recent(limit=50, kind="approval") if r.subject_id == "model_test_1"),
            key=lambda r: r.created_at,
        )
        assert len(recs) == 2, "one audit BEFORE download, one AFTER"
        assert recs[0].status == "ok" and "approved and starting" in recs[0].summary
        assert recs[0].principal == "tester"
        assert recs[0].approvals == ["tester"]
        assert recs[1].status == "ok" and "completed and registered" in recs[1].summary
        assert recs[1].detail["final_size_gb"] == 0.9
        assert recs[1].detail["checksum"] == "abc123"
    finally:
        await db.close()


async def test_apply_rejected_when_hardware_recheck_fails(tmp_path: Path) -> None:
    dl = FakeDownload()
    # Card needs 1.5 GiB VRAM — fits discovery box (2.0) but NOT the live
    # re-check (1.0): proves stale discovery fit is never trusted.
    tighter = HardwareProfile(gpu_available=True, vram_gb=1.0, ram_gb=15.6, cpu_cores=12, free_disk_gb=99.0)
    proposer, repo, audit, registry, gate, db, _ = await make_stack(
        tmp_path, download=dl, gateway_hw=tighter
    )
    try:
        await proposer.propose(make_proposal(make_card(min_vram=1.5)))

        try:
            await gate.apply("model_test_1", approved=True)
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError when live hardware no longer fits")

        assert all(c.identity.name != "tiny-model" for c in registry.all())
        assert dl.calls == [], "download must not start when re-check fails"
        recs = await audit.list_recent(limit=50, kind="approval")
        assert len(recs) == 1
        assert recs[0].status == "failed"
        assert "hardware re-check failed" in recs[0].summary
    finally:
        await db.close()


async def test_failed_download_stays_candidate_and_audits_failure(tmp_path: Path) -> None:
    dl = FakeDownload(DownloadResult(success=False, error="no space left on device"))
    proposer, repo, audit, registry, gate, db, _ = await make_stack(tmp_path, download=dl)
    try:
        await proposer.propose(make_proposal(make_card()))

        out = await gate.apply("model_test_1", approved=True)

        assert out.status == "candidate", "failed download must leave proposal as candidate"
        assert all(c.identity.name != "tiny-model" for c in registry.all()), "nothing registered on failure"
        recs = sorted(
            (r for r in await audit.list_recent(limit=50, kind="approval") if r.subject_id == "model_test_1"),
            key=lambda r: r.created_at,
        )
        assert len(recs) == 2
        assert recs[0].status == "ok"
        assert recs[1].status == "failed"
        assert "no space left on device" in recs[1].reasoning
    finally:
        await db.close()


async def test_download_exception_audits_failure(tmp_path: Path) -> None:
    dl = FakeDownload(exc=RuntimeError("boom"))
    proposer, repo, audit, registry, gate, db, _ = await make_stack(tmp_path, download=dl)
    try:
        await proposer.propose(make_proposal(make_card()))
        out = await gate.apply("model_test_1", approved=True)

        assert out.status == "candidate"
        assert all(c.identity.name != "tiny-model" for c in registry.all())
        recs = await audit.list_recent(limit=50, kind="approval")
        failures = [r for r in recs if r.status == "failed" and "exception" in r.summary]
        assert len(failures) == 1
        assert "boom" in failures[0].reasoning
    finally:
        await db.close()


async def test_apply_unknown_proposal_raises_keyerror(tmp_path: Path) -> None:
    proposer, repo, audit, registry, gate, db, dl = await make_stack(tmp_path)
    try:
        try:
            await gate.apply("not-there", approved=True)
        except KeyError:
            pass
        else:
            raise AssertionError("expected KeyError for unknown proposal")
        assert dl.calls == []
    finally:
        await db.close()


# -- retire -------------------------------------------------------------------


async def test_retire_removes_from_routing_and_audits(tmp_path: Path) -> None:
    proposer, repo, audit, registry, gate, db, _ = await make_stack(tmp_path)
    try:
        await proposer.propose(make_proposal(make_card()))
        await gate.apply("model_test_1", approved=True, approver="tester")
        assert "tiny-model" in {c.identity.name for c in registry.all()}

        retired = await gate.retire("tiny-model", approver="tester", reason="no longer needed")

        assert retired.identity.name == "tiny-model"
        assert "tiny-model" not in {c.identity.name for c in registry.all()}
        recs = await audit.list_recent(limit=50, kind="approval")
        retired_recs = [r for r in recs if r.subject_id == "tiny-model" and "retired" in r.summary]
        assert len(retired_recs) == 1
        assert retired_recs[0].principal == "tester"
    finally:
        await db.close()


async def test_retire_unknown_model_raises_keyerror(tmp_path: Path) -> None:
    proposer, repo, audit, registry, gate, db, _ = await make_stack(tmp_path)
    try:
        try:
            await gate.retire("never-registered")
        except KeyError:
            pass
        else:
            raise AssertionError("expected KeyError for unknown model")
    finally:
        await db.close()


async def test_retired_model_is_not_chosen_by_router(tmp_path: Path) -> None:
    proposer, repo, audit, registry, gate, db, _ = await make_stack(tmp_path)
    registry.cards.clear()
    try:
        await proposer.propose(
            make_proposal(make_card("tiny-retirable", min_vram=1.0, min_ram=4.0, param_count_b=0.5))
        )
        await gate.apply("model_test_1", approved=True)
        before = registry.cheapest_sufficient(needs_tools=False)
        assert before is not None and before.identity.name == "tiny-retirable"  # cheapest (0.5B)

        await gate.retire("tiny-retirable")
        after = registry.cheapest_sufficient(needs_tools=False)
        assert after is None or after.identity.name != "tiny-retirable"
    finally:
        await db.close()


# -- repository round-trip ----------------------------------------------------


async def test_proposal_repository_roundtrips_full_model_card(tmp_path: Path) -> None:
    proposer, repo, audit, registry, gate, db, _ = await make_stack(tmp_path)
    try:
        card = make_card(min_vram=1.5, min_ram=6.0)
        await proposer.propose(make_proposal(card, proposal_id="roundtrip_1"))

        fetched = await repo.get("roundtrip_1")
        assert fetched is not None
        got = fetched.model_card

        assert got.identity.name == card.identity.name
        assert got.identity.provider == card.identity.provider
        assert got.architecture.param_count_b == card.architecture.param_count_b
        assert got.capabilities.chat is True
        assert got.reasoning is ReasoningLevel.BASIC
        assert got.tool_use is ToolUseSupport.PROMPTED_ONLY
        assert got.context_window_tokens == 8192
        assert got.memory_requirements.min_vram_gb == 1.5
        assert got.memory_requirements.min_ram_gb == 6.0
        assert got.quantization_supported == ["int4"]
        assert got.runtime_compatibility == [RuntimeTarget.LLAMA_CPP]
        assert got.license == "Apache 2.0"
        assert got.cost.input_per_million_tokens_usd == 0.1
        assert got.reliability.consistency == "medium"
        assert fetched.status == "candidate"
        assert fetched.source_url == "https://example/model"
    finally:
        await db.close()
