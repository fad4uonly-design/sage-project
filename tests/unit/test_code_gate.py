"""Unit tests for the code application gate (Phase 4).

Mirrors the Evolver / ModelGate safety-chain test style. Proves:
- LOW risk + passing sandbox auto-applies WITHOUT approval (audit before+after)
- HIGH risk NEVER auto-applies even when sandbox passes (stays candidate)
- approved=False raises PermissionError; LOW-risk apply() raises ValueError
- failed sandbox tests never apply regardless of risk level (both paths)
- audit BEFORE + AFTER entries exist on every write path (auto + approved)
- apply() RE-RUNS the sandbox on live content — it never trusts the stale
  propose-time sandbox_result (swap the content after propose, watch it refuse)
- path escape (../) and own-safety-mechanism writes are refused
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sage.audit.logger import AuditLogger
from sage.core.code_gate import (
    CodeApplicationService,
    CodeProposalRepository,
    CodeProposalService,
    CodeProposalStatus,
)
from sage.core.code_sandbox import CodeSandbox, SandboxResult
from sage.core.risk_classifier import ProposedChange
from sage.db.connection import Database
from sage.db.migrations import apply_migrations

PASS_CODE = "VALUE = 42"
PASS_TEST = "def run_tests():\n    assert VALUE == 42\n"
FAIL_TEST = "def run_tests():\n    raise AssertionError('boom')\n"
PASS_RESULT = SandboxResult(passed=True, output="ok")
FAIL_RESULT = SandboxResult(passed=False, output="", error="boom")


def low_change(file_path: str = "sage/tools/generated_helper.py") -> ProposedChange:
    return ProposedChange(
        file_path=file_path,
        is_new_file=True,
        diff_or_content=PASS_CODE,
        description="generated helper",
    )


def high_change() -> ProposedChange:
    return ProposedChange(
        file_path="sage/core/engine.py",
        is_new_file=False,
        diff_or_content=PASS_CODE,
        description="edit to existing core file",
    )


async def make_stack(tmp_path: Path) -> tuple[
    CodeProposalService,
    CodeApplicationService,
    AuditLogger,
    Database,
    Path,
]:
    code_root = tmp_path / "repo"
    code_root.mkdir(parents=True, exist_ok=True)
    db = Database(tmp_path / "code_gate.db")
    await db.open()
    await apply_migrations(db)
    repo = CodeProposalRepository(db)
    await repo.ensure_table()
    audit = AuditLogger(db)
    proposer = CodeProposalService(repo)
    applier = CodeApplicationService(
        repo, audit, CodeSandbox(timeout_seconds=20), code_root=code_root
    )
    return proposer, applier, audit, db, code_root


async def approval_entries(audit: AuditLogger, proposal_id: str) -> list:
    return [
        r
        for r in await audit.list_recent(limit=100, kind="approval")
        if r.subject_id == proposal_id
    ]


async def test_low_risk_passing_auto_applies_without_approval(
    tmp_path: Path,
) -> None:
    proposer, applier, audit, db, code_root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=low_change(), sandbox_result=PASS_RESULT, test_code=PASS_TEST
        )
        assert proposal.status is CodeProposalStatus.CANDIDATE
        out = await applier.evaluate(proposal.proposal_id)
        assert out.status is CodeProposalStatus.AUTO_APPLIED
        target = code_root / "sage" / "tools" / "generated_helper.py"
        assert target.read_text(encoding="utf-8") == PASS_CODE
        recs = await approval_entries(audit, proposal.proposal_id)
        assert len(recs) == 2
        summaries = [(r.summary or "") for r in recs]
        assert any("about to be applied" in s for s in summaries)
        assert any("applied (auto_apply)" in s for s in summaries)
    finally:
        await db.close()


async def test_high_risk_never_auto_applies_even_when_tests_pass(
    tmp_path: Path,
) -> None:
    proposer, applier, audit, db, code_root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=high_change(), sandbox_result=PASS_RESULT, test_code=PASS_TEST
        )
        out = await applier.evaluate(proposal.proposal_id)
        assert out.status is CodeProposalStatus.CANDIDATE
        assert not (code_root / "sage" / "core" / "engine.py").exists()
        recs = await approval_entries(audit, proposal.proposal_id)
        assert len(recs) == 1
        assert "held for review" in (recs[0].summary or "").lower()
    finally:
        await db.close()


async def test_failed_sandbox_never_auto_applies_even_when_low_risk(
    tmp_path: Path,
) -> None:
    proposer, applier, _audit, db, code_root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=low_change(), sandbox_result=FAIL_RESULT, test_code=FAIL_TEST
        )
        out = await applier.evaluate(proposal.proposal_id)
        assert out.status is CodeProposalStatus.CANDIDATE
        assert not (code_root / "sage" / "tools" / "generated_helper.py").exists()
    finally:
        await db.close()


async def test_apply_requires_explicit_approval(tmp_path: Path) -> None:
    proposer, applier, _audit, db, _root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=high_change(), sandbox_result=PASS_RESULT, test_code=PASS_TEST
        )
        with pytest.raises(PermissionError):
            await applier.apply(proposal.proposal_id, approved=False)
    finally:
        await db.close()


async def test_apply_rejects_low_risk_proposals(tmp_path: Path) -> None:
    proposer, applier, _audit, db, _root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=low_change(), sandbox_result=PASS_RESULT, test_code=PASS_TEST
        )
        with pytest.raises(ValueError, match="LOW risk"):
            await applier.apply(proposal.proposal_id, approved=True)
    finally:
        await db.close()

async def test_approved_high_risk_applies_with_audit_pair(tmp_path: Path) -> None:
    proposer, applier, audit, db, code_root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=ProposedChange(
                file_path="sage/skills/generated_skill.py",
                is_new_file=False,
                diff_or_content=PASS_CODE,
                description="high-risk edit with passing tests",
            ),
            sandbox_result=PASS_RESULT,
            test_code=PASS_TEST,
        )
        out = await applier.apply(proposal.proposal_id, approved=True)
        assert out.status is CodeProposalStatus.APPROVED
        assert (code_root / "sage" / "skills" / "generated_skill.py").exists()
        recs = await approval_entries(audit, proposal.proposal_id)
        assert len(recs) == 2
    finally:
        await db.close()


async def test_apply_reruns_sandbox_not_stale_result(tmp_path: Path) -> None:
    proposer, applier, audit, db, code_root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=ProposedChange(
                file_path="sage/skills/stale_skill.py",
                is_new_file=False,
                diff_or_content=PASS_CODE,
                description="stale passing result, live content fails",
            ),
            sandbox_result=PASS_RESULT,
            test_code=FAIL_TEST,
        )
        out = await applier.apply(proposal.proposal_id, approved=True)
        assert out.status is CodeProposalStatus.CANDIDATE
        assert not (code_root / "sage" / "skills" / "stale_skill.py").exists()
        recs = await approval_entries(audit, proposal.proposal_id)
        assert len(recs) == 1
        assert recs[0].status == "failed"
    finally:
        await db.close()


async def test_apply_with_failing_tests_never_writes(tmp_path: Path) -> None:
    proposer, applier, _audit, db, code_root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=ProposedChange(
                file_path="sage/skills/broken_skill.py",
                is_new_file=False,
                diff_or_content="BROKEN = (",
                description="broken content",
            ),
            sandbox_result=FAIL_RESULT,
            test_code=FAIL_TEST,
        )
        out = await applier.apply(proposal.proposal_id, approved=True)
        assert out.status is CodeProposalStatus.CANDIDATE
        assert not (code_root / "sage" / "skills" / "broken_skill.py").exists()
    finally:
        await db.close()


async def test_reject_marks_rejected_with_audit(tmp_path: Path) -> None:
    proposer, applier, audit, db, code_root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=low_change(), sandbox_result=PASS_RESULT, test_code=PASS_TEST
        )
        out = await applier.reject(proposal.proposal_id, "not needed")
        assert out.status is CodeProposalStatus.REJECTED
        assert not (code_root / "sage" / "tools" / "generated_helper.py").exists()
        recs = await approval_entries(audit, proposal.proposal_id)
        assert len(recs) == 1
    finally:
        await db.close()


async def test_path_escape_is_refused(tmp_path: Path) -> None:
    proposer, applier, _audit, db, _root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=ProposedChange(
                file_path="../escape.py",
                is_new_file=True,
                diff_or_content=PASS_CODE,
                description="escape attempt",
            ),
            sandbox_result=PASS_RESULT,
            test_code=PASS_TEST,
        )
        with pytest.raises(ValueError, match="[Ee]scape"):
            await applier.apply(proposal.proposal_id, approved=True)
    finally:
        await db.close()


async def test_own_safety_mechanism_writes_refused(tmp_path: Path) -> None:
    proposer, applier, _audit, db, code_root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=ProposedChange(
                file_path="sage/core/code_gate.py",
                is_new_file=True,
                diff_or_content=PASS_CODE,
                description="self-modification attempt",
            ),
            sandbox_result=PASS_RESULT,
            test_code=PASS_TEST,
        )
        with pytest.raises(PermissionError, match="own safety mechanism"):
            await applier.apply(proposal.proposal_id, approved=True)
        assert not (code_root / "sage" / "core" / "code_gate.py").exists()
    finally:
        await db.close()


async def test_evaluate_rejects_non_candidates(tmp_path: Path) -> None:
    proposer, applier, _audit, db, _root = await make_stack(tmp_path)
    try:
        proposal = await proposer.propose(
            change=low_change(), sandbox_result=PASS_RESULT, test_code=PASS_TEST
        )
        await applier.evaluate(proposal.proposal_id)
        with pytest.raises(ValueError, match="candidates"):
            await applier.evaluate(proposal.proposal_id)
    finally:
        await db.close()

