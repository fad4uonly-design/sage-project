"""Generic approval-gated reversible filesystem change mechanism.

This module operates only on an explicitly supplied target workspace. It has no
SAGE knowledge and is never called by the default Part 3 workflow.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from ..approval.binding import (
    ApprovalBindingService,
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
)
from ..evidence import deterministic_id, sha256_digest
from ..packaging.proposed import SubmittedPackage
from ..regression.framework import RegressionComparison


@dataclass(frozen=True, slots=True)
class FileChange:
    operation: str
    relative_path: str
    before_digest: str | None
    after_content: bytes | None
    after_digest: str | None

    def __post_init__(self) -> None:
        if self.operation not in {"ADD", "UPDATE", "REMOVE"}:
            raise ValueError("invalid file change operation")
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("change path must be relative and traversal-free")
        if self.operation in {"ADD", "UPDATE"}:
            if self.after_content is None or sha256_digest(self.after_content) != self.after_digest:
                raise ValueError("after content/digest mismatch")


@dataclass(frozen=True, slots=True)
class ChangeSetV3:
    change_set_id: str
    changes: tuple[FileChange, ...]
    context_paths: tuple[str, ...] = ()

    @property
    def digest(self) -> str:
        return sha256_digest(
            {
                "id": self.change_set_id,
                "changes": [
                    {
                        "operation": item.operation,
                        "path": item.relative_path,
                        "before": item.before_digest,
                        "after": item.after_digest,
                    }
                    for item in self.changes
                ],
                "context_paths": list(self.context_paths),
            }
        )


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    relative_path: str
    existed: bool
    digest: str | None
    stored_path: str | None


@dataclass(frozen=True, slots=True)
class TargetSnapshotV3:
    snapshot_id: str
    target_root_digest: str
    entries: tuple[SnapshotEntry, ...]
    snapshot_digest: str


@dataclass(frozen=True, slots=True)
class ApplicationResult:
    outcome: str
    snapshot: TargetSnapshotV3 | None
    applied_paths: tuple[str, ...]
    rollback_outcome: str | None
    regression_verdict: str | None
    problem: str | None


class ReversibleApplicationManager:
    def __init__(
        self,
        *,
        target_root: Path,
        snapshot_root: Path,
        approval_service: ApprovalBindingService,
        fail_restore_paths: frozenset[str] = frozenset(),
    ) -> None:
        self.target_root = target_root.resolve()
        self.snapshot_root = snapshot_root.resolve()
        self.approval_service = approval_service
        self.fail_restore_paths = fail_restore_paths
        self.target_root.mkdir(parents=True, exist_ok=True)
        self.snapshot_root.mkdir(parents=True, exist_ok=True)

    def apply(
        self,
        *,
        change_set: ChangeSetV3,
        submitted: SubmittedPackage,
        approval_request: ApprovalRequestRecord,
        approval_decision: ApprovalDecisionRecord,
        preflight: RegressionComparison,
        post_regression: Callable[[], RegressionComparison],
    ) -> ApplicationResult:
        if not self.approval_service.verify(
            approval_decision, approval_request, submitted
        ):
            return ApplicationResult("BLOCKED", None, (), None, None, "approval invalid")
        package = self.approval_service.store.read(submitted)
        if package["security_assessment"]["verdict"] == "BLOCKED":
            return ApplicationResult("BLOCKED", None, (), None, None, "security assessment is blocking")
        if package["change_set"]["digest"] != change_set.digest:
            return ApplicationResult("BLOCKED", None, (), None, None, "change set scope mismatch")
        if not preflight.passed:
            return ApplicationResult("BLOCKED", None, (), None, preflight.verdict, "preflight regression failed")
        paths = tuple(
            dict.fromkeys(
                [item.relative_path for item in change_set.changes]
                + list(change_set.context_paths)
            )
        )
        try:
            snapshot = self.capture_snapshot(paths)
            self._verify_preconditions(change_set)
            applied = self._apply_changes(change_set)
            post = post_regression()
            if not post.passed:
                rollback = self.rollback(snapshot)
                return ApplicationResult(
                    "ROLLED_BACK" if rollback == "PASS" else "ROLLBACK_FAILED",
                    snapshot,
                    applied,
                    rollback,
                    post.verdict,
                    "post-application regression failed",
                )
            return ApplicationResult("APPLIED", snapshot, applied, None, post.verdict, None)
        except Exception as exc:
            if "snapshot" in locals():
                rollback = self.rollback(snapshot)
                return ApplicationResult(
                    "ROLLED_BACK" if rollback == "PASS" else "ROLLBACK_FAILED",
                    snapshot,
                    tuple(locals().get("applied", ())),
                    rollback,
                    None,
                    str(exc),
                )
            return ApplicationResult("FAILED_CLOSED", None, (), None, None, str(exc))

    def capture_snapshot(self, paths: tuple[str, ...]) -> TargetSnapshotV3:
        entries = []
        for relative in paths:
            path = self._path(relative)
            if path.is_symlink():
                raise ValueError("snapshot refuses symlink target")
            if path.exists():
                if not path.is_file():
                    raise ValueError("snapshot supports regular files only")
                data = path.read_bytes()
                digest = sha256_digest(data)
                stored = self.snapshot_root / digest.removeprefix("sha256:")
                if not stored.exists():
                    stored.write_bytes(data)
                    os.chmod(stored, 0o400)
                entries.append(SnapshotEntry(relative, True, digest, str(stored)))
            else:
                entries.append(SnapshotEntry(relative, False, None, None))
        material = [
            {"path": item.relative_path, "existed": item.existed, "digest": item.digest}
            for item in entries
        ]
        digest = sha256_digest(material)
        return TargetSnapshotV3(
            snapshot_id=deterministic_id("target-snapshot", digest),
            target_root_digest=sha256_digest(str(self.target_root)),
            entries=tuple(entries),
            snapshot_digest=digest,
        )

    def rollback(self, snapshot: TargetSnapshotV3) -> str:
        failures = []
        for entry in snapshot.entries:
            try:
                if entry.relative_path in self.fail_restore_paths:
                    raise OSError("injected rollback failure")
                target = self._path(entry.relative_path)
                if entry.existed:
                    stored = Path(entry.stored_path or "")
                    data = stored.read_bytes()
                    if sha256_digest(data) != entry.digest:
                        raise ValueError("snapshot artifact digest mismatch")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_suffix(target.suffix + ".rollback.tmp")
                    temporary.write_bytes(data)
                    os.replace(temporary, target)
                elif target.exists():
                    if target.is_file() and not target.is_symlink():
                        target.unlink()
                    else:
                        raise ValueError("rollback refuses non-file target")
            except Exception:
                failures.append(entry.relative_path)
        return "FAIL" if failures else "PASS"

    def _verify_preconditions(self, change_set: ChangeSetV3) -> None:
        for change in change_set.changes:
            target = self._path(change.relative_path)
            current = sha256_digest(target.read_bytes()) if target.exists() else None
            if current != change.before_digest:
                raise ValueError(f"before digest mismatch: {change.relative_path}")

    def _apply_changes(self, change_set: ChangeSetV3) -> tuple[str, ...]:
        applied = []
        for change in change_set.changes:
            target = self._path(change.relative_path)
            if change.operation == "REMOVE":
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".apply.tmp")
                temporary.write_bytes(change.after_content or b"")
                os.replace(temporary, target)
            applied.append(change.relative_path)
        return tuple(applied)

    def _path(self, relative: str) -> Path:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("target path escapes root")
        target = (self.target_root / Path(*pure.parts)).resolve()
        target.relative_to(self.target_root)
        return target
