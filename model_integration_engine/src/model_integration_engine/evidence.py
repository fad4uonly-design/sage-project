"""Canonical hashing and evidence construction for Phase 2.

Evidence identifiers are deterministic for the same subject, observation,
collector, and source content. Collection time is retained but does not change
identity, which makes fixture runs reproducible.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .domain import (
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    EvidenceRecord,
    JSONValue,
    SourceRef,
    SubjectRef,
)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON-compatible data deterministically for local hashing.

    This is not the final production package-signing canonicalization profile;
    it is stable for Phase 2 identity/evidence and is labeled accordingly.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_digest(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical_json_bytes(value)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def deterministic_id(prefix: str, *parts: Any) -> str:
    digest = sha256_digest(list(parts)).removeprefix("sha256:")
    return f"{prefix}:{digest[:32]}"


@dataclass(frozen=True, slots=True)
class EvidenceFactory:
    collector_id: str
    collector_version: str
    clock: Clock = utc_now

    def create(
        self,
        *,
        kind: EvidenceKind,
        level: EvidenceLevel,
        subject: SubjectRef,
        observation_key: str,
        observed_value: JSONValue,
        source_uri: str,
        source_digest: str | None,
        locator: str | None,
        outcome: EvidenceOutcome | None = None,
        environment_id: str | None = None,
        derived_from: tuple[str, ...] = (),
        supersedes: tuple[str, ...] = (),
        redacted: bool = False,
    ) -> EvidenceRecord:
        evidence_id = deterministic_id(
            "evidence",
            self.collector_id,
            self.collector_version,
            subject.kind.value,
            subject.subject_id,
            subject.digest,
            observation_key,
            observed_value,
            source_digest,
            locator,
            level.value,
            outcome.value if outcome else None,
            list(derived_from),
        )
        return EvidenceRecord(
            evidence_id=evidence_id,
            kind=kind,
            level=level,
            subject=subject,
            observation_key=observation_key,
            observed_value=observed_value,
            source=SourceRef(
                uri=source_uri,
                digest=source_digest,
                locator=locator,
            ),
            collector_id=self.collector_id,
            collector_version=self.collector_version,
            collected_at=self.clock(),
            outcome=outcome,
            environment_id=environment_id,
            derived_from=derived_from,
            supersedes=supersedes,
            redacted=redacted,
        )
