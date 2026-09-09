"""Code gate — approval-gated application of auto-generated code changes.

Phase 4 of the autonomy roadmap. Mirrors the propose/apply separation proven
in ``sage/evolver/service.py`` and ``sage/core/model_gate.py``:

    CodeProposalService      — stores candidate proposals. ZERO side effects:
                               no files written, no sandbox executed. Risk is
                               stamped by the deterministic classifier
                               (``sage/core/risk_classifier.py``) at propose
                               time.
    CodeApplicationService   — the ONLY class allowed to write generated
                               files onto the real filesystem, and only when
                               EVERY check passes:
                                 (a) LOW risk AND sandbox passed -> evaluate()
                                     auto-applies (audit BEFORE + AFTER)
                                 (b) HIGH risk -> stays 'candidate' until a
                                     human explicitly approves via apply()
                                 (c) apply() requires ``approved=True`` or
                                     raises PermissionError
                                 (d) apply() RE-RUNS the sandbox on live
                                     ``diff_or_content`` + ``test_code`` — never
                                     trusts the stale propose-time result
                                 (e) every file write flows through ONE
                                     method (_write_file) so audit coverage
                                     cannot be bypassed
                                 (f) path-escape and self-modification
                                     (own sandbox/classifier/gate files) are
                                     refused even if classification says LOW

CRITICAL SAFETY RULE: no file is ever written by propose/evaluate alone.
High-risk changes require a human ``approved=True``. A change only
auto-applies when BOTH the sandbox passed AND the risk classifier stamped
LOW — and any ambiguity in classification defaults to HIGH.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from sage.audit.logger import AuditLogger
from sage.core.code_sandbox import CodeSandbox, SandboxResult
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.core.risk_classifier import (
    GATE_OWN_FILES,
    ProposedChange,
    RiskLevel,
    classify,
)
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event
from sage.logging import get_logger
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class CodeProposalStatus(str, Enum):
    CANDIDATE = "candidate"
    AUTO_APPLIED = "auto_applied"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CodeProposal:
    """A proposed code change awaiting sandbox + risk + (if needed) approval."""

    proposal_id: str
    change: ProposedChange
    sandbox_result: SandboxResult
    risk_level: RiskLevel
    status: CodeProposalStatus = CodeProposalStatus.CANDIDATE
    reasoning: str = ""
    created_at: str = field(default_factory=utcnow_iso)
    #: The test code used at propose time; re-run live by apply().
    test_code: str = ""


def _proposal_id() -> str:
    return new_id("chg")


# -- ProposedChange / SandboxResult <-> JSON (storage round-trip) -------------


def _change_to_dict(change: ProposedChange) -> dict[str, Any]:
    return {
        "file_path": change.file_path,
        "is_new_file": change.is_new_file,
        "diff_or_content": change.diff_or_content,
        "description": change.description,
    }


def _change_from_dict(data: dict[str, Any]) -> ProposedChange:
    return ProposedChange(
        file_path=data["file_path"],
        is_new_file=bool(data.get("is_new_file", False)),
        diff_or_content=data.get("diff_or_content", ""),
        description=data.get("description", ""),
    )


class CodeProposalRepository(BaseRepository):
    """Data access layer for code proposals (mirrors ModelProposalRepository)."""

    def __init__(self, db: Database) -> None:
        super().__init__(db)

    async def ensure_table(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS code_proposals (
                proposal_id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                is_new_file INTEGER NOT NULL DEFAULT 0,
                diff_or_content TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                test_code TEXT NOT NULL DEFAULT '',
                sandbox_result_json TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'candidate',
                reasoning TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )

    async def insert(self, proposal: CodeProposal) -> None:
        await self.db.execute(
            """
            INSERT INTO code_proposals (
                proposal_id, file_path, is_new_file, diff_or_content, description,
                test_code, sandbox_result_json, risk_level, status, reasoning, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal.proposal_id,
                proposal.change.file_path,
                1 if proposal.change.is_new_file else 0,
                proposal.change.diff_or_content,
                proposal.change.description,
                proposal.test_code,
                self.dumps(asdict(proposal.sandbox_result)),
                proposal.risk_level.value,
                proposal.status.value if isinstance(proposal.status, CodeProposalStatus) else proposal.status,
                proposal.reasoning,
                proposal.created_at,
            ),
        )

    async def get(self, proposal_id: str) -> CodeProposal | None:
        row = await self.db.fetchone(
            "SELECT * FROM code_proposals WHERE proposal_id = ?", (proposal_id,)
        )
        if row is None:
            return None
        return self._row_to_proposal(row)

    async def list_all(self, *, limit: int = 50) -> list[CodeProposal]:
        rows = await self.db.fetchall(
            "SELECT * FROM code_proposals ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [self._row_to_proposal(r) for r in rows]

    async def update_status(self, proposal_id: str, status: CodeProposalStatus) -> None:
        status_val = status.value if isinstance(status, CodeProposalStatus) else status
        await self.db.execute(
            "UPDATE code_proposals SET status = ? WHERE proposal_id = ?",
            (status_val, proposal_id),
        )

    def _row_to_proposal(self, row: Any) -> CodeProposal:
        sr = self.loads(row["sandbox_result_json"], {})
        return CodeProposal(
            proposal_id=row["proposal_id"],
            change=ProposedChange(
                file_path=row["file_path"],
                is_new_file=bool(row["is_new_file"]),
                diff_or_content=row["diff_or_content"],
                description=row["description"],
            ),
            sandbox_result=SandboxResult(
                passed=bool(sr.get("passed", False)),
                output=str(sr.get("output", "")),
                error=sr.get("error"),
                duration_seconds=float(sr.get("duration_seconds", 0.0)),
            ),
            risk_level=RiskLevel(row["risk_level"]),
            status=CodeProposalStatus(row["status"]),
            reasoning=row["reasoning"],
            created_at=row["created_at"],
            test_code=row["test_code"],
        )


class CodeProposalService:
    """Isolated service dedicated strictly to storing candidate proposals.

    Safety Guarantee:
    - ZERO side effects: no file writes, no sandbox execution, no network.
      Only persists a candidate + stamps the deterministic risk level.
    """

    def __init__(
        self,
        repo: CodeProposalRepository,
        events: EventBus | None = None,
    ) -> None:
        self._repo = repo
        self._events = events

    async def propose(
        self,
        *,
        change: ProposedChange,
        sandbox_result: SandboxResult,
        reasoning: str = "",
        test_code: str = "",
    ) -> CodeProposal:
        """Store a new candidate proposal (always status='candidate')."""
        proposal = CodeProposal(
            proposal_id=_proposal_id(),
            change=change,
            sandbox_result=sandbox_result,
            risk_level=classify(change),
            status=CodeProposalStatus.CANDIDATE,
            reasoning=reasoning,
            test_code=test_code,
        )
        await self._repo.insert(proposal)
        log.info(
            "code_gate.proposed",
            id=proposal.proposal_id,
            file=change.file_path,
            risk=proposal.risk_level.value,
        )
        if self._events:
            await self._events.publish(
                Event(
                    type="code.proposal_created",
                    payload={
                        "proposal_id": proposal.proposal_id,
                        "file_path": change.file_path,
                        "risk_level": proposal.risk_level.value,
                    },
                    source="code_gate",
                )
            )
        return proposal

    async def get(self, proposal_id: str) -> CodeProposal | None:
        return await self._repo.get(proposal_id)

    async def list_proposals(self, *, limit: int = 50) -> list[CodeProposal]:
        return await self._repo.list_all(limit=limit)


class CodeApplicationService:
    """The ONLY class allowed to write generated files onto the real
    filesystem. Mirror of Evolver/ModelGate ApplicationService: explicit
    approval, live re-checks, audit BEFORE and AFTER, and a single write path
    so audit coverage cannot be bypassed.
    """

    def __init__(
        self,
        repo: CodeProposalRepository,
        audit: AuditLogger,
        sandbox: CodeSandbox,
        *,
        code_root: Path,
        events: EventBus | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._sandbox = sandbox
        self._code_root = code_root.resolve()
        self._events = events

    async def evaluate(self, proposal_id: str) -> CodeProposal:
        """Auto-apply ONLY if risk is LOW AND the stored sandbox result passed.

        HIGH risk or failed sandbox -> stays 'candidate', NOT written, and a
        held-for-review audit entry is recorded. Requires an explicit apply()
        approval to proceed.
        """
        proposal = await self._repo.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Code proposal not found: {proposal_id}")
        if proposal.status != CodeProposalStatus.CANDIDATE:
            raise ValueError(
                f"Code proposal {proposal_id} is '{proposal.status.value}'; "
                "evaluate() only accepts candidates."
            )

        if proposal.risk_level == RiskLevel.LOW and proposal.sandbox_result.passed:
            await self._write_file(
                proposal,
                principal="system",
                reason="auto-applied: LOW risk and sandbox passed",
                action="auto_apply",
            )
            await self._repo.update_status(proposal_id, CodeProposalStatus.AUTO_APPLIED)
            applied = await self._reload(proposal_id)
            await self._publish(
                "code.change_auto_applied",
                proposal_id,
                applied.change.file_path,
            )
            return applied

        reason_held = (
            "risk HIGH" if proposal.risk_level != RiskLevel.LOW else "sandbox did not pass"
        )
        await self._record(
            proposal_id=proposal_id,
            principal="system",
            status="ok",
            summary=f"Code change held for review: {reason_held}",
            reasoning=proposal.reasoning,
            detail={
                "file_path": proposal.change.file_path,
                "risk_level": proposal.risk_level.value,
                "sandbox_passed": proposal.sandbox_result.passed,
            },
        )
        log.info(
            "code_gate.held",
            id=proposal_id,
            file=proposal.change.file_path,
            reason=reason_held,
        )
        return proposal

    async def apply(
        self,
        proposal_id: str,
        *,
        approved: bool,
        approver: str = "user",
        reason: str | None = None,
    ) -> CodeProposal:
        """Approve and apply a HIGH-risk proposal.

        - APPROVED=False (or missing) -> PermissionError.
        - LOW-risk proposals are NOT handled here (they belong to evaluate()).
        - Re-runs the sandbox on the live content+test BEFORE writing — never
          trusts the stale propose-time result. A failing re-run leaves the
          proposal as 'candidate' and records a failed audit entry.
        """
        if not approved:
            raise PermissionError(
                f"Code proposal {proposal_id} cannot be applied: "
                "explicit approval flag is False."
            )

        proposal = await self._repo.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Code proposal not found: {proposal_id}")
        if proposal.status != CodeProposalStatus.CANDIDATE:
            raise ValueError(
                f"Code proposal {proposal_id} is '{proposal.status.value}'; "
                "apply() only accepts candidates."
            )
        if proposal.risk_level == RiskLevel.LOW:
            raise ValueError(
                f"Code proposal {proposal_id} is LOW risk; it is applied "
                "automatically by evaluate(). apply() is for high-risk proposals."
            )

        # (d) LIVE sandbox re-run — never trust the stored sandbox_result.
        fresh = await self._sandbox.run(
            proposal.change.diff_or_content,
            proposal.test_code,
        )
        if not fresh.passed:
            await self._record(
                proposal_id=proposal_id,
                principal=approver,
                status="failed",
                summary="Code change apply refused — live sandbox re-test failed",
                reasoning=f"approval given but sandbox re-run failed: {fresh.error}",
                detail={
                    "file_path": proposal.change.file_path,
                    "approver": approver,
                    "sandbox_output": fresh.output[:2000],
                    "sandbox_error": fresh.error,
                },
            )
            log.warning(
                "code_gate.apply_refused",
                id=proposal_id,
                file=proposal.change.file_path,
                error=fresh.error,
            )
            return proposal  # stays candidate

        await self._write_file(
            proposal,
            principal=approver,
            reason=reason or "approved via code gate",
            action="apply",
        )
        await self._repo.update_status(proposal_id, CodeProposalStatus.APPROVED)
        applied = await self._reload(proposal_id)
        await self._publish("code.change_applied", proposal_id, applied.change.file_path)
        return applied

    async def reject(self, proposal_id: str, reason: str) -> CodeProposal:
        """Mark a candidate proposal as rejected (no file written)."""
        proposal = await self._repo.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Code proposal not found: {proposal_id}")
        if proposal.status != CodeProposalStatus.CANDIDATE:
            raise ValueError(
                f"Code proposal {proposal_id} is '{proposal.status.value}'; "
                "only candidates can be rejected."
            )

        await self._record(
            proposal_id=proposal_id,
            principal="system",
            status="ok",
            summary="Code change rejected",
            reasoning=reason,
            detail={"file_path": proposal.change.file_path},
        )
        await self._repo.update_status(proposal_id, CodeProposalStatus.REJECTED)
        await self._publish("code.change_rejected", proposal_id, proposal.change.file_path)
        return await self._reload(proposal_id)

    # -- Single write path -----------------------------------------------------
    # Every file write in this module flows through _write_file, so the
    # audit-before/after pair and the safety refusals can never be skipped.

    async def _write_file(
        self,
        proposal: CodeProposal,
        *,
        principal: str,
        reason: str,
        action: str,
    ) -> Path:
        target = self._resolve_target(proposal.change.file_path)
        self._assert_not_own_file(target)
        detail = {
            "file_path": proposal.change.file_path,
            "target": str(target),
            "risk_level": proposal.risk_level.value,
            "action": action,
        }
        await self._record(
            proposal_id=proposal.proposal_id,
            principal=principal,
            status="ok",
            summary=f"Code change about to be applied ({action})",
            reasoning=reason,
            detail=detail,
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(proposal.change.diff_or_content, encoding="utf-8")
        except OSError as exc:
            await self._record(
                proposal_id=proposal.proposal_id,
                principal=principal,
                status="failed",
                summary="Code change write FAILED",
                reasoning=str(exc),
                detail=detail,
            )
            log.exception("code_gate.write_failed", id=proposal.proposal_id)
            raise
        await self._record(
            proposal_id=proposal.proposal_id,
            principal=principal,
            status="ok",
            summary=f"Code change applied ({action}): {proposal.change.file_path}",
            reasoning=reason,
            detail={**detail, "bytes": len(proposal.change.diff_or_content.encode("utf-8"))},
        )
        log.info(
            "code_gate.written",
            id=proposal.proposal_id,
            file=proposal.change.file_path,
            action=action,
        )
        return target

    def _resolve_target(self, file_path: str) -> Path:
        """Resolve file_path against code_root, refusing any escape."""
        root = self._code_root
        raw = Path(file_path)
        if raw.is_absolute():
            raise ValueError(
                f"code gate refuses absolute file paths: {file_path!r}"
            )
        target = (root / raw).resolve()
        if not target.is_relative_to(root):
            raise ValueError(
                f"code gate refuses a path that escapes the code root: {file_path!r}"
            )
        return target

    def _assert_not_own_file(self, target: Path) -> None:
        """Defense-in-depth: never write to the auto-coder's own safety
        mechanism, even if a proposed change somehow classified LOW."""
        try:
            rel = target.relative_to(self._code_root)
        except ValueError:
            return
        rel_str = rel.as_posix()
        if rel_str in GATE_OWN_FILES:
            raise PermissionError(
                f"code gate refuses to modify its own safety mechanism: {rel_str}"
            )

    async def _record(
        self,
        *,
        proposal_id: str,
        principal: str,
        status: str,
        summary: str,
        reasoning: str,
        detail: dict[str, Any],
    ) -> None:
        await self._audit.record(
            kind="approval",
            subject_id=proposal_id,
            principal=principal,
            status=status,
            summary=summary,
            reasoning=reasoning,
            approvals=[principal],
            detail=detail,
        )

    async def _reload(self, proposal_id: str) -> CodeProposal:
        prop = await self._repo.get(proposal_id)
        if prop is None:
            raise RuntimeError(f"Code proposal vanished: {proposal_id}")
        return prop

    async def _publish(self, event_type: str, proposal_id: str, file_path: str) -> None:
        if self._events is None:
            return
        await self._events.publish(
            Event(
                type=event_type,
                payload={"proposal_id": proposal_id, "file_path": file_path},
                source="code_gate",
            )
        )


class CodeGateModule(BaseModule):
    """Lifecycle and DI module for the code gate subsystem."""

    name = "code_gate"
    version = "0.7.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._proposer: CodeProposalService | None = None
        self._applier: CodeApplicationService | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        try:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS code_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    is_new_file INTEGER NOT NULL DEFAULT 0,
                    diff_or_content TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    test_code TEXT NOT NULL DEFAULT '',
                    sandbox_result_json TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    reasoning TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_code_proposals_status ON code_proposals(status);
                """
            )
        except Exception:
            log.exception("code_gate.table_init_failed")

        audit = self.container.resolve(AuditLogger)
        events = self.container.try_resolve(EventBus)
        repo = CodeProposalRepository(db)
        # Code root = repository root (parents of sage/core/code_gate.py).
        code_root = Path(__file__).resolve().parents[2]
        sandbox = CodeSandbox()

        self._proposer = CodeProposalService(repo, events)
        self._applier = CodeApplicationService(
            repo,
            audit,
            sandbox,
            code_root=code_root,
            events=events,
        )

        self.container.register_instance(CodeProposalRepository, repo)
        self.container.register_instance(CodeProposalService, self._proposer)
        self.container.register_instance(CodeApplicationService, self._applier)
        self.container.register_instance(CodeSandbox, sandbox)

    async def _on_health(self) -> HealthStatus | None:
        if self._proposer is None or self._applier is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(self.name, "ok")
