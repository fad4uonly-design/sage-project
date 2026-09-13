"""Approval request/decision binding to exact immutable scope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..evidence import sha256_digest, utc_now
from ..packaging.proposed import ImmutablePackageStore, SubmittedPackage


@dataclass(frozen=True, slots=True)
class ApprovalRequestRecord:
    request_id: str
    package_id: str
    package_digest: str
    change_set_digest: str
    target_snapshot_digest: str
    permission_set_digest: str
    policy_digest: str
    rollback_plan_digest: str
    scope_digest: str
    created_at: datetime
    state: str = "PENDING_HUMAN_APPROVAL"


@dataclass(frozen=True, slots=True)
class ApprovalDecisionRecord:
    request_id: str
    scope_digest: str
    package_digest: str
    decision: str
    actor_id: str
    decided_at: datetime
    authentication_ref: str


class ApprovalBindingService:
    def __init__(self, store: ImmutablePackageStore, clock=utc_now) -> None:
        self.store = store
        self.clock = clock

    def create_request(self, submitted: SubmittedPackage) -> ApprovalRequestRecord:
        document = self.store.read(submitted)
        material = document["approval_binding_material"]
        scope = {
            "package_digest": submitted.package_digest,
            **dict(material),
        }
        scope_digest = sha256_digest(scope)
        return ApprovalRequestRecord(
            request_id="approval-request:" + scope_digest.removeprefix("sha256:")[:32],
            package_id=submitted.package_id,
            package_digest=submitted.package_digest,
            change_set_digest=material["change_set_digest"],
            target_snapshot_digest=material["target_snapshot_digest"],
            permission_set_digest=material["permission_set_digest"],
            policy_digest=material["policy_digest"],
            rollback_plan_digest=material["rollback_plan_digest"],
            scope_digest=scope_digest,
            created_at=self.clock(),
        )

    def record_human_decision(
        self,
        request: ApprovalRequestRecord,
        *,
        decision: str,
        actor_id: str,
        authentication_ref: str,
        human_authority: bool,
    ) -> ApprovalDecisionRecord:
        if not human_authority:
            raise PermissionError("only authenticated human authority may decide")
        if decision not in {"APPROVED", "REJECTED", "CHANGES_REQUESTED"}:
            raise ValueError("invalid approval decision")
        if not actor_id or not authentication_ref:
            raise ValueError("approval actor and authentication reference are required")
        return ApprovalDecisionRecord(
            request_id=request.request_id,
            scope_digest=request.scope_digest,
            package_digest=request.package_digest,
            decision=decision,
            actor_id=actor_id,
            decided_at=self.clock(),
            authentication_ref=authentication_ref,
        )

    def verify(
        self,
        decision: ApprovalDecisionRecord,
        request: ApprovalRequestRecord,
        submitted: SubmittedPackage,
    ) -> bool:
        if decision.decision != "APPROVED":
            return False
        if not self.store.verify(submitted):
            return False
        current = self.create_request(submitted)
        return (
            decision.request_id == request.request_id == current.request_id
            and decision.scope_digest == request.scope_digest == current.scope_digest
            and decision.package_digest == submitted.package_digest == request.package_digest
            and bool(decision.actor_id)
            and bool(decision.authentication_ref)
        )
